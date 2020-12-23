import uuid
import json
import logging
import datetime

import umsg
import pytest

import vmtmock as vmtconnect
import quarantine

umsg.init(level=logging.DEBUG)
umsg.add_handler(logging.StreamHandler)

def generate_action(actionType, createTime, actionState):
    return {
        "uuid": str(uuid.uuid4()),
        "createTime": createTime.isoformat(),
        "actionType": actionType,
        "actionState": actionState
    }

def generate_failures(actionType, times=1, createTime=datetime.datetime.now()):
    return [generate_action(actionType, createTime, 'FAILED') for a in range(times)]

def generate_successes(actionType, times=1, createTime=datetime.datetime.now()):
    return [generate_action(actionType, createTime, 'SUCCEEDED') for a in range(times)]


test_failures_in_a_row_data = [
    (2, None, [{"uuid": str(uuid.uuid4()), "actions": generate_failures('MOVE', 2)}], True),
    # Only once in a row, but two required
    (2, None, [{"uuid": str(uuid.uuid4()), "actions": generate_failures('MOVE') + generate_successes('MOVE')}], False),
    (3, None, [{"uuid": str(uuid.uuid4()), "actions": generate_failures('MOVE', 3)}], True),
    (4, None, [{"uuid": str(uuid.uuid4()), "actions": generate_failures('MOVE', 4)}], True),
]

test_failures_x_out_of_y_data = [
    (2, 3, [{"uuid": str(uuid.uuid4()), "actions": generate_successes('MOVE', 1) + generate_failures('MOVE', 2)}], True),
    (2, 5, [{"uuid": str(uuid.uuid4()), "actions": generate_successes('MOVE', 3) + generate_failures('MOVE', 2)}], True),
    (2, 5, [{"uuid": str(uuid.uuid4()), "actions": generate_successes('MOVE') + generate_failures('MOVE') + generate_successes('MOVE', 2) + generate_failures('MOVE')}], True),
]

@pytest.mark.parametrize("times,tries,payload,assertion", test_failures_in_a_row_data + test_failures_x_out_of_y_data)
def test_failures_in_a_row(times, tries, payload, assertion):
    vmt = vmtconnect.Session(responses={
        "request": [payload]
    })
    asdto = {
        "actionItem": [
            {
                "actionType": "MOVE",
                "uuid": str(uuid.uuid4()),
                "targetSE": {
                    "turbonomicInternalId": str(uuid.uuid4())
                }
            }
        ]
    }
    rule = {
        "actionType": "MOVE",
        # "entityType": "VIRTUAL_MACHINE",
        "failureCount": times,
        "attemptCount": tries,
        "quarantineMethods": []
    }
    d = quarantine.Diagnostician(rule, quarantine.WardFactory(quarantine.VmtJit()), logger=umsg.get_attr("logger"))
    assert d.diagnose(vmt, quarantine.Patient(asdto, logger=umsg.get_attr("logger"))) == assertion
