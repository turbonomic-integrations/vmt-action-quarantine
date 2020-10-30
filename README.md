# Turbonomic Failed Action Quarantine
This integration is intended to be run as a POST action orchestration step and
quarantine service entities if they have met certain criteria for failed attempts
of the same action.

# Prerequisites
Deploying this solution stands up a Kubernetes pod which serves SSH, and gets
added to Turbonomic as an orchestration target.

This requires the following prerequisites (also documented in [docker-orchestration](https://github.com/turbonomic-integrations/docker-orchestration)).
* SSH Daemon Host Key (public and private)
  * This is used to uniquely identify the SSH "host", in this case, the single running pod in Kubernetes which hosts this integration.
* SSH User Authorized Key (public and private)
  * This is used to uniquely identify the SSH "user" which is authorized to connect to the SSH Daemon.
* Turbonomic API Service Account Username & Password

To generate a host key and user key the following commands can be used
(ProTip: Do *NOT* set a passphrase for the keys.);
```
$ ssh-keygen -t rsa -f ./hostkey -C "quarantine actionscript hostkey"
$ ssh-keygen -t rsa -f ./turboauthorizedkey -C "quarantine actionscript turbo user key"
```

Once you have both sets of keys, and the credentials for a Turbonomic API Service Account (assumed to be administrator:administrator here), these can all be securely stored in Kubernetes with this command;
```
$ kubectl create secret generic quarantinekeys -n turbointegrations \
--from-file=hostkey --from-file=hostkey.pub \
--from-file=turboauthorizedkey --from-file=turboauthorizedkey.pub \
--from-literal=turbouser=administrator --from-literal=turbopass=administrator
$ kubectl label secret quarantinekeys -n turbointegrations \
environment=prod \
team=turbointegrations \
app=quarantine
```

## Configuration
In order to quarantine entities based on your desired rules, you'll need to configure

* Your desired rules (config.yaml)
* This project to expose a script for the Entity and Action type(s) desired (manifest.json)
* Turbonomic Policy to execute the script for the Entity and Action type(s) desired.

Each of these will be covered in more detail below.
### Rules (Config)
The configuration file (config.yaml) will contain rules for criteria a given
entity must meet in order to be quarantined, and the means by which it should
be quarantined.

You may have many rules, which may match different action and entity types, and
which may quarantine separately.

The configuration file is a YAML file, the root level object has one property
named `quarantineRules` which is an array of quarantine rules, like so.

```
---
quarantineRules:
- <rule 1>
- <rule 2>
```

Each rule has the following properties;
* `actionType`
  * The Turbonomic action type to match I.E. ("RESIZE", "MOVE", etc)
  * Required
* `entityType`
  * The Turbonomic entity type to match I.E. ("VIRTUAL_MACHINE","PHYSICAL_MACHINE", etc)
  * Required
* `lookbackHours`
  * The number of hours into the past to look for historical action results.
  * Optional (Default: 720)
* `failureCount`
  * The number of times that the same action type must fail before the entity
    will be quarantined. When `attemptCount` is not set, this is the number of
    times the action must fail consecutively.
  * Optional (Default: 1)
* `attemptCount`
  * When set the same action type must fail `failureCount` out of `attemptCount`
    times to be quarantined.
  * Optional
* `quarantineMethods`
  * An array of objects describing methods which will be used to quarantine the
    entity if it meets the criteria defined. This will be discussed in detail
    later in the [document](#quarantinemethods).
  * Required (but may be blank if no action is desired.)

Thus, a minimal configuration would be;
```
---
quarantineRules:
- actionType: MOVE
  entityType: VIRTUAL_MACHINE
  quarantineMethods: []
```

This configuration would match all Virtual Machine Move actions, but would not
take any action.

#### Quarantine Methods
Currently, only one method for quarantine exists. Future methods may be added.

Every quarantine method requires exactly one parameter, namely the `type` of
quarantine method. The current list of supported types is `vmt`.

#### Vmt Quarantine Method
This quarantine method uses a static Turbonomic group for quarantine. When an
entity matches a quarantine rule, it will be added to the static group.

If the static group does not exist at the time of quarantine, it will be created.

The `vmt` quarantine method has two required parameters.

* `groupName`
  * The display name of the Turbonomic Static Group
  * Required
* `groupType`
  * The Turbonomic entity type of the Static Group (used to create the group).
  * Required

Thus, a minimal configuration with a fully formed `vmt` quarantine method
would look like;
```
---
quarantineRules:
- actionType: MOVE
  entityType: VIRTUAL_MACHINE
  quarantineMethods:
  - type: vmt
    groupName: QuarantineVM
    groupType: VirtualMachine
```

In fact, this rule configuration is exactly what is in the included `config.yaml`

### Manifest
Turbonomic must be configured to know that this script can be executed as
custom orchestration for certain types of actions.

This is accomplished by manipulating the included `manifest.json` which
currently has one entry which informs Turbonomic that it may use this script
for `MOVE` actions applied to `VIRTUAL_MACHINE` entities in the `POST` `actionPhase`
of orchestration.

It is advised that the `actionPhase` be left at `POST`. This indicates that the script
would be run *after* the event has been executed, and will allow the script to
determine the success or failure of that action, and any actions which
preceded it.

You must also leave `scriptPath` set to `/opt/turbonomic/actionscripts/quarantine/quarantine.py`.
This tells Turbonomic where in the deployed pod the script resides, and can
not be changed.

If you wish to match multiple action and entity types, an additional entry in
the `scripts` array is required for each. For example, a manifest which allows
execution of this script for both `RESIZE` and `MOVE` actions on a
`VIRTUAL_MACHINE` would look like this.

```
{
 "scripts": [
   	{
   		"name": "Quarantine VM MOVE",
   		"description": "Quarantines VMs after move, based on critera set in the config file.",
   		"scriptPath": "/opt/turbonomic/actionscripts/quarantine/quarantine.py",
   		"entityType": "VIRTUAL_MACHINE",
   		"actionType": "MOVE",
  		"actionPhase": "POST"
   	},    
  	{
  		"name": "Quarantine VM RESIZE",
  		"description": "Quarantines VMs after resize, based on critera set in the config file.",
  		"scriptPath": "/opt/turbonomic/actionscripts/quarantine/quarantine.py",
  		"entityType": "VIRTUAL_MACHINE",
  		"actionType": "RESIZE",
 		  "actionPhase": "POST"
  	}
  ]
}
```

### Policy
Finally, you will need to create a custom Turbonomic automation policy which
will trigger this script upon the completion of certain actions.

This step can not be completed until the solution is completely deployed.
If you have not yet deployed the pod in your Kubernetes cluster, please
complete the steps in [Deployment](#deployment), then return here to configure
your policy.

# Deployment
Once you have satisfied the [#prerequisites], and configured this project and
Turbonomic appropriately [#configuration], you are now ready to deploy this
integration to your Kubernetes cluster.

First, save the configurations you've prepared with the following command;
```
$ kubectl create configmap quarantinecfg -n turbointegrations \
--from-file=config.yaml --from-file=manifest.json
$ kubectl label configmap quarantinecfg -n turbointegrations \
environment=prod \
team=turbointegrations \
app=quarantine
```

Then, you may deploy the actual pod which will host the integration.

```
$ kubectl apply -f deployment.yaml
```
