#!/opt/venv/bin/python

import os
import sys
import json
import logging

from typing import List

import umsg
import yaml
import vmtconnect
import configargparse

# import com.vmware.cis.tagging_client
from pyVmomi import vim, vmodl
from pyVim.connect import SmartConnectNoSSL, Disconnect

try:
    import iso8601
    def read_isodate(date):
        return iso8601.parse_date(date)
except ModuleNotFoundError:
    try:
        import dateutil.parser
        def read_isodate(date):
            return dateutil.parser.parse(date)
    except ModuleNotFoundError:
        raise Exception('Unable to import pyiso8601 or python-dateutil.')


class VmtJit:
    """A thin wrapper for the :py:class:`~vmtconnect.Connection` and
    :py:class:`~vmtconnect.Session` classes which delays instantiation until
    it's actually required.

    This is useful for situations where you need to initialize the object,
    perhaps from a configuration or args, but may not use the connection so
    the login and version checks would be unecessary
    """

    def __init__(self, *args, **kwargs):
        """Initialize a :py:class:`~VmtJit`.

        Accepts all args used to instantiate a
        :py:class:`~vmtconnect.Connection`
        """
        self.args = args
        self.kwargs = kwargs
        self.vmt = None

    def get_connection(self) -> vmtconnect.Connection:
        """Returns a :class:`vmtconnect.Connection` instantiated with the
        arguments supplied on initialization.

        The returned object is cached, so subsequent requests will return the
        same instance of :class:`vmtconnect.Connection`, even if it was
        instatiated by :func:`~get_session`
        """
        if not self.vmt:
            self.vmt = vmtconnect.Connection(*self.args, **self.kwargs)
        return self.vmt

    def get_session(self) -> vmtconnect.Connection:
        """Returns a :py:class:`vmtconnect.Connection` instantiated with the
        arguments supplied on initialization, plus the `use_session` arg set
        to True

        The returned object is cached, so subsequent requests will return the
        same instance of :py:class:`~vmtconnect.Connection`, even if it was
        instatiated by :func:`~get_connection
        """
        if not self.vmt:
            self.vmt = vmtconnect.Session(*self.args, **self.kwargs)
        return self.vmt


class Event:
    """A thin wrapper for the VMT action DTO.

    Arguments:
        actionDto (dict): An action DTO from either the action script
            orchestration probe, or the Turbonomic API.

    Attributes:
        actionType (str): The Turbonomic action type.
        entityType (str): The Turbonomic entity type acted upon.
        uuid (str): The UUID of the action.
        result (:obj:`str`): The result of the action, can be None when
            instantiated from orchestration probe.
        createTime (:obj:`datetime`): The creation time of the action, can be
            None when instantiated from orchestration probe.

    """

    def __init__(self, actionDto):
        self.actionType = actionDto['actionType']
        self.entityType = actionDto.get('targetSE', {}).get('entityType')
        self.uuid = actionDto['uuid']
        self.result = actionDto.get('actionState')
        self.createTime = actionDto.get('createTime')


class Patient:
    """A thin wrapper for the VMT entity DTO.

    Arguments:
        actionScriptDto (dict): The JSON DTO sent to stdin of an action script.

    Attributes:
        triggerEvent (:obj:`~Event`): An Event containing the details which can
            be gleaned from the action script orchestration probe DTO.
        uuid (str): The UUID of the Entity
        tags (list): A list of available tags, only populated after
            :func:`~Patient.get_entity` is executed.
        vendorIds (dict): The vendorIds map, only populated after
            :func:`~Patient.get_entity` is executed.
    """

    def __init__(self, actionScriptDto):
        entity = actionScriptDto['actionItem'][0]['targetSE']
        self.triggerEvent = Event(actionScriptDto['actionItem'][0])
        self.actionState = actionScriptDto['actionState']
        self.uuid = entity['turbonomicInternalId']
        self.tags = []
        self.vendorIds = {}

    def get_entity(self, vmt: vmtconnect.Connection):
        """Fetch additional details about the patient.

        Queries the entity from the VMT API to fetch additional details which
        are not included in the action script orchestration probe DTO.

        Arguments:
            vmt (:obj:`~vmtconnect.Connection`): An instantiated vmtconnect
                connection, used to make the API request.
        """
        entity = vmt.get_entities(uuid=self.uuid)[0]
        self.tags = entity.get('tags', [])
        self.vendorIds = entity.get('vendorIds', {})

    def get_events(self, vmt: vmtconnect.Connection, lookbackHours: int) \
            -> List[Event]:
        """Fetch historical events for the patient.

        Queries previous actions which occurred between the lookbackHours and
        now.

        Arguments:
            vmt (:obj:`~vmtconnect.Connection`): An instantiated vmtconnect
                connection, used to make the API request.
            lookbackHours (int): Number of hours into the past to query.
        """
        actionsDto = {
            "actionInput": {
                "startTime": f"-{lookbackHours}h",
                "endTime": "-0d",
                "actionTypeList": [
                    self.triggerEvent.actionType
                ],
                "actionStateList": [
                    "SUCCEEDED",
                    "FAILED"
                ]
            }
        }
        actions = vmt.request(
            'actions', method='POST', dto=json.dumps(actionsDto))[0]
        return [Event(e) for e in actions]


class Ward:
    """Abstract base class for admitting and discharging patients."""

    def admit(self, patient: Patient):
        """Adds a patient to quarantine.

        To be implemented by inheriting classes."""
        pass

    def discharge(self, patient: Patient):
        """Removes a patient from quarantine.

        To be implemented by inheriting classes."""
        pass

    def discharge_eligible_patients(self) -> List[Patient]:  # type: ignore
        """Removes all patients from quarantine meeting the criteria.

        To be implemented by inheriting classes."""
        pass


class VmtWard(Ward):
    """Implementation of :py:class:`~Ward` for Turbonomic static groups.

    Quarantine is accomplished by adding or removing the entity from a static
    group.

    Arguments:
        vmtjit (:obj:`~VmtJit`): An instance of the JIT wrapper for
            :py:class:`~vmtconnect.Connection` used for API calls.
        config (dict): Config details for this `quarantineMethod` in the
            config.yaml

    Attributes:
        vmtjit (:obj:`~VmtJit`): An instance of the JIT wrapper for
            :py:class:`~vmtconnect.Connection` used for API calls.
        group_name (str): The name of the static group to use for quarantine.
        group_type (str): The entity type of the static group. This is only
            used when creating the static group.

    Example:
    Given a config file like;
    ```
    ---
    quarantineRules:
    - actionType: MOVE
      lookbackHours: 720
      failureCount: 1
      quarantineMethods:
      - type: vmt
        groupName: Quarantine
        groupType: VirtualMachine
    ```

    This Ward will add or remove entities to a static group named "Quarantine"
    """
    def __init__(self, vmtjit: VmtJit, config):
        self.vmtjit = vmtjit
        self.group_name = config['groupName']
        self.group_type = config['groupType']
        self.group = None

    def _get_group(self):
        if not self.group:
            # umsg.log(f"Group Name to lookup: {self.group_name}")
            # group = self.vmtjit.get_session() \
            #     .get_group_by_name(self.group_name)
            group = self.vmtjit.get_session() \
                .search(types=['Group'],q=self.group_name)
            if not group:
                self.group = self.vmtjit.get_session() \
                    .add_static_group(self.group_name, self.group_type)[0]
            else:
                self.group = group[0]
        return self.group

    def admit(self, patient: Patient):
        """Add the patient (Entity) to the defined static group.

        If the group does not exist, it will be created using the group name
        and type provided when instantiating this Ward

        Arguments:
            patient (:obj:`~Patient`): The patient (Entity) to quarantine.
        """
        vmt = self.vmtjit.get_session()
        vmt.add_static_group_members(
            self._get_group()['uuid'], [patient.uuid])

    def discharge(self, patient: Patient):
        """Remove the patient (Entity) from the defined static group.

        Arguments:
            patient (:obj:`~Patient`): The patient (Entity) to remove from
                quarantine.
        """
        vmt = self.vmtjit.get_session()
        group_uuid = self._get_group()['uuid']
        members = vmt.get_group_members(group_uuid)
        new_members = [m for m in members if m['uuid'] != patient.uuid]
        vmt.update_static_group_members(group_uuid, new_members)

    def discharge_eligible_patients(self):
        """Remove all patients (Entities) from the defined static group."""
        vmt = self.vmtjit.get_session()
        group_uuid = self._get_group()['uuid']
        members = vmt.get_group_members(group_uuid)
        vmt.update_static_group_members(group_uuid, [])
        return [Patient(m) for m in members]


class VcenterWard(Ward):
    def __init__(self, hostname, user, passwd, config):
        self.hostname = hostname
        self.vc = SmartConnectNoSSL(host=self.hostname, user=user, pwd=passwd)
        self.tag_category = config['tag']['category']

    def _findVm(self, patient: Patient):
        # VM lookup adapted from Richard Stern's `vm_reset.py` which is
        # adapted from https://github.com/vmware/pyvmomi-community-samples/blob/master/samples/tools/pchelper.py
        view = self.vc.content.viewManager.CreateContainerView(
            self.vc.content.rootFolder, [vim.VirtualMachine], True)

        collector = self.vc.content.propertyCollector

        traversal_spec = vmodl.query.PropertyCollector.TraversalSpec()
        traversal_spec.name = 'traverseEntities'
        traversal_spec.path = 'view'
        traversal_spec.skip = False
        traversal_spec.type = view.__class__

        obj_spec = vmodl.query.PropertyCollector.ObjectSpec()
        obj_spec.selectSet = [traversal_spec]
        obj_spec.obj = view
        obj_spec.skip = True

        property_spec = vmodl.query.PropertyCollector.PropertySpec()
        property_spec.type = vim.VirtualMachine
        property_spec.pathSet = ['name']

        filter_spec = vmodl.query.PropertyCollector.FilterSpec()
        filter_spec.objectSet = [obj_spec]
        filter_spec.propSet = [property_spec]

        pset = collector.RetrieveContents([filter_spec])

        idx = 0
        for obj in pset:
            print(idx)
            idx = idx + 1
            for x in obj.propSet:
                print(f"{x.name}: {x.val}")
            if obj.obj._moId == patient.vendorIds[self.hostname]:
                return obj.obj

        return None

    def admit(self, patient: Patient):
        vm = self._findVm(patient)
        for opt in vm.tag:
            print(f"{opt.key}:{opt.value}")

    def discharge(self, patient: Patient):
        pass

    def discharge_eligible_patients(self):
        pass


class WardFactory:
    """Instantiates the known :py:class:`~Ward` types, holding them in a cache.

    Arguments:
        vmtjit (:obj:`~VmtJit`): An instance of the JIT wrapper for
            :py:class:`~vmtconnect.Connection`. This is "special" for the
            :py:class:`~VmtWard` since an instance of VmtJit is expected to
            already exist which can be shared with any instance(s) of the Ward.
    """
    def __init__(self, vmt: VmtJit):
        self._vmt = vmt
        self._ward_cache = {}

    def _unique_ward_key(self, config):
        if config['type'] == 'vmt':
            return f"{config['type']}-{config['groupName']}"
        return config['type']

    def get_ward(self, config):
        """Return a new or cached instance of the requested :py:class:`~Ward`

        Arguments:
            config (dict): The config map, which *must* have a `type` property
                to indicate the ward type, and any additional config properties
                for the given Ward type.

        Returns:
            The requested :py:class:`~Ward`

        See also:
            :py:class:`~Ward`
            :py:class:`~VmtWard`
            :py:class:`~VcenterWard` (Incomplete)
        """
        if self._unique_ward_key(config) not in self._ward_cache:
            if config['type'] == 'vmt':
                ward = VmtWard(self._vmt, config)
                self._ward_cache[self._unique_ward_key(config)] = ward
            else:
                self._ward_cache[self._unique_ward_key(config)] = Ward()
        return self._ward_cache[self._unique_ward_key(config)]

    def all_wards(self):
        """Return all cached instances of :py:class:`~Ward`."""
        return self._ward_cache.values()


class Diagnostician:
    """Contains the ruleset for matching conditions requiring quarantine.

    Arguments:
        quarantineRuleConfig (dict): Config details for this `quarantineRule`
            in the config.yaml
        wardFactory (:obj:`~WardFactory`): An instance of :py:class:`~WardFactory`

    Attributes:
        actionType (str): The VMT action type I.E. ("RESIZE", "MOVE", etc)
        entityType (str): The type of entity to act upon I.E.
            ("VIRTUAL_MACHINE","PHYSICAL_MACHINE", etc)
        lookbackHours (int): The number of hours into the past to look for
            historical action results. default: 720
        failureCount (int): The number of times that the same action type must
            fail before the entity will be quarantined. When `attemptCount` is
            not set, this is the number of times the action must fail
            consecutively.
        attemptCount (:obj:`int`): When set the same action type must fail
            `failureCount` out of `attemptCount` times to be quarantined.
        wards (list): List of :py:class:`~Ward` where the patient will be
            quarantined if the criteria are met.
    """

    def __init__(self, quarantineRuleConfig, wardFactory: WardFactory):
        self.actionType = quarantineRuleConfig['actionType']
        self.entityType = quarantineRuleConfig.get('entityType')
        self.lookbackHours = quarantineRuleConfig.get('lookbackHours', 720)
        self.failureCount = quarantineRuleConfig.get('failureCount', 1)
        self.attemptCount = quarantineRuleConfig.get('attemptCount')
        self.wards = []
        for ward in quarantineRuleConfig['quarantineMethods']:
            self.wards.append(wardFactory.get_ward(ward))

    def triage(self, patient: Patient):
        """Verify the patient's triggering event matches criteria.

        Quickly qualify the current event before potentially getting more
        information about the patient, or the patients events.

        For example, if the action script DTO is for a "MOVE" action type, but
        this diagnostician is looking for "RESIZE" events, this will return
        false.

        Return:
            `True` if triage criteria is met, `False` otherwise.
        """

        umsg.log(f"Diag Action Type: {self.actionType}, Patient Trigger Action: {patient.triggerEvent.actionType} ")
        umsg.log(f"Diag Entity Type: {self.entityType}, Patient Entity Action: {patient.triggerEvent.entityType} ")
        if self.actionType == patient.triggerEvent.actionType and \
           not self.entityType:
            return True
        if self.actionType == patient.triggerEvent.actionType and \
           self.entityType == patient.triggerEvent.entityType:
            return True
        return False

    def diagnose(self, vmt: vmtconnect.Connection, patient: Patient):
        """Fetch additional patient information and render diagnosis.

        Makes an API call to fetch action history for the patient (Entity) and
        uses that data to render a diagnosis.

        Arguments:
            vmt (:obj:`~vmtconnect.Connection`): A vmtconnect instance
                used to request action history.
            patient (:obj:`~Patient`): The patient to consider against
                this diagnostician's ruleset.

        Returns:
            `True` if the patient should be quarantined based on this
            diagnostician's ruleset, `False` otherwise.
        """
        if self.failureCount == 1 and patient.actionState in ['FAILING', 'FAILED']:
            diagnosed = True
        else:
            try:
                events = patient.get_events(vmt, self.lookbackHours)
                sortedEvents = sorted(
                    events,
                    key=lambda action: read_isodate(action.createTime))

                if self.attemptCount:
                    sortedEvents = sortedEvents[self.attemptCount*-1:]

                failedActions = [
                    a for a in sortedEvents
                    if a.result and a.result.lower() == 'failed']

                umsg.log(f"Failed Actions Count: {len(failedActions)}, Tolerable Failed Actions {self.failureCount}")
                diagnosed = len(failedActions) >= self.failureCount
                # TODO: Implement class mixin for umsg correctly.
                # if diagnosed:
                #     umsg.log(
                #         f"Patient {patient.uuid} diagnosed with {len(failedActions)} "
                #         f"failed actions out of {len(sortedEvents)}", level="Debug")
                
            except IndexError:
                umsg.log(f"{self.failureCount} failed actions required for admitting, but no events were returned in lookup")
                diagnosed = False

        umsg.log(f"Patient needs admitting: {diagnosed}") if diagnosed else None
        return diagnosed

    def admit(self, patient: Patient):
        """Admit the patient to all wards under this diagnostician's charge.

        Arguments:
            patient (:obj:`~Patient`): The patient (Entity) to quarantine.
        """
        for ward in self.wards:
            ward.admit(patient)

    def discharge(self, patient: Patient):
        """Discharge the patient from all wards under this diagnostician's charge.

        Arguments:
            patient (:obj:`~Patient`): The patient (Entity) to remove from
                quarantine.
        """
        for ward in self.wards:
            ward.discharge(patient)

    def criteria(self):
        """Return a user readable description of the criteria for quarantine."""
        retval = f"Fail {self.entityType} {self.actionType} actions " \
            f"{self.failureCount}"
        if self.attemptCount:
            retval += f" out of {self.attemptCount} attempts."
        else:
            retval += " in a row."

        return retval


if __name__ == '__main__':
    parser = configargparse.ArgumentParser(
        description="Action script for quarantining Service Entities based on"
        " config criteria."
    )

    parser.add(
        "-c", "--config-file", env_var="CONFIGFILE",
        help="Full file path to a yaml configuration file."
        "(default:/opt/turbonomic/actionscripts/quarantine/config/config.yaml)",
        default="/opt/turbonomic/actionscripts/quarantine/config/config.yaml")

    parser.add("-u", "--vmt-user", env_var="VMT_USERNAME",
               help="Turbonomic OpsMgr username.")

    parser.add("-p", "--vmt-pass", env_var="VMT_PASSWORD",
               help="Turbonomic OpsMgr password.")

    parser.add("--vmt-host", type=str, env_var="VMT_HOST",
               help="Hostname or IP of the Turbonomic OpsMgr "
               "(default: api.turbonomic.svc.cluster.local:8080)",
               default="api.turbonomic.svc.cluster.local:8080")
    parser.add("--logfile", type=str, env_var="LOGFILE",
               help="File destination for logging. (default: /var/log/stdout)",
               default="/var/log/stdout")

    parser.add("--vmt-ssl", action="store_true", env_var="VMT_SSL")
    parser.add("--debug", action="store_true", env_var="DEBUG")

    parser.add("--discharge", action="store_true", env_var="DISCHARGE")

    args = parser.parse_args()

    umsg.init(level=logging.DEBUG if args.debug else logging.INFO)
    handler = logging.FileHandler(args.logfile)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)
    umsg.add_handler(handler)

    try:
        if args.vmt_user and args.vmt_pass:
            vmtjit = VmtJit(args.vmt_host, username=args.vmt_user,
                            password=args.vmt_pass, ssl=args.vmt_ssl)
        else:
            ba_str = vmtconnect.security.Credential().decrypt()
            vmtjit = VmtJit(
                args.vmt_host, auth=ba_str, ssl=args.vmt_ssl)

        ward_factory = WardFactory(vmtjit)

        with open(args.config_file) as cfgfile:
            config = yaml.load(cfgfile, Loader=yaml.FullLoader)

        # Capture all of urllib3's warnings SSL verification
        logging.captureWarnings(True)

        diagnosticians = []

        # This executes if admitting or discharging, since it instantiates
        # the wards in the ward factory.
        for rule in config['quarantineRules']:
            diagnosticians.append(Diagnostician(rule, ward_factory))
        
        umsg.log(f"Diagnosticians: {diagnosticians}")
        umsg.log(f"Diagnosticians: {diagnosticians}",)

        if args.discharge:
            for ward in ward_factory.all_wards():
                ward.discharge_eligible_patients()
        else:
            entity_name = os.environ.get('VMT_TARGET_NAME')
            umsg.log(
                f"Processing POST action script for {entity_name}")

            stdinDto = json.loads(sys.stdin.read())
            patient = Patient(stdinDto)

            for diagnostician in diagnosticians:
                umsg.log(f"Testing Diagnostician: {diagnostician}")
                if diagnostician.triage(patient):
                    umsg.log(f"Patient {entity_name} needs to be diagnosed")
                    if diagnostician.diagnose(vmtjit.get_session(), patient):
                        patient.get_entity(vmtjit.get_session())
                        diagnostician.admit(patient)
                        umsg.log(
                            f"Quarantined {entity_name} matching criteria - "
                            f"{diagnostician.criteria()}")
    except Exception as e:
        umsg.log(f"Exception {e}", exc_info=True, level="Error")
