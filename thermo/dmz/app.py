"""
This lives on the WWW.

Accept backend long-poll connections from trusted zone. (with trust token)

Accept request; redirect to google auth, if success push to backend long poll

Backend will return result in next query, with association ID. 

Long-term, make the backend connection into a TCP based queue (connection is awkward bit)
"""

from collections import defaultdict
from datetime import datetime
import os
from typing import Dict, Union, Optional

from flask import Flask, request, send_from_directory
from pydantic import BaseModel

JSON = Union[Dict, str, int]

class ZoneRequest(BaseModel):
    security_token: str
    zone_name: str
    threading_id: str
    payload: JSON
    
class ZoneReply(BaseModel):
    threading_id: str
    method: str  # enum Timeout | ReadEnv | SendTemp

class Sensors(BaseModel):
    temp_centigrade: Optional[float] = None
    humid_percent: Optional[float] = None
    created_dt: str = "" 

    def model_post_init(self, __context) -> None:
        if not self.created_dt:
            self.created_dt = datetime.now().isoformat()

class IRCommand(BaseModel):
    lolidk: str = ""
    created_dt: str = ""
    last_access_dt: str = "" 

    def model_post_init(self, __context) -> None:
        if not self.created_dt:
            self.created_dt = datetime.now().isoformat()

    def model_mark_accessed(self) -> None:
        self.last_access_dt = datetime.now().isoformat()

class ZoneState(BaseModel):
    command: Optional[IRCommand] = None
    sensors: Optional[Sensors] = None

app = Flask(__name__) 

def assertAuthAzZone(req):
    # skip auth for now, but let's treat house info as 'sensitive', later. 
    assert req

### BEGIN STATE (make this sqlite)
commands = defaultdict(list) # {zonename -> [IRCommand]}
sensors = defaultdict(list) # {zonename -> [ Sensors]}
### END STATE 

def _lastor(lst, default=None):
    if not lst: return default
    return lst[-1]

def _zone_response(zonename, update_access) -> JSON:
    """Craft the json for one zone's response"""
    # which happens to be exactly the UpdateZone model
    cmd = _lastor(commands[zonename])
    sns = _lastor(sensors[zonename])
    if cmd and update_access:
        cmd.model_mark_accessed()
    ret = ZoneState(command = cmd, sensors= sns).model_dump()
    print(f"_zone_response({zonename}, {update_access}) -> {ret}")
    return ret

MAXLEN = 10000

def _append_and_trim(lst, item):
    """Append an item to the lst, and trim it to max length."""
    # eventually, this goes into a DB, and we will use some history subsampling. 
    # eg: daily at noon for ever, hourly for last year, by minute last month.....
    lst.append(item)
    while len(lst) > MAXLEN:
        # I don't care if this is possibly slow if there are many to delete.
        # we call this on every append
        del lst[0]
        
# FIXME: soonish, make separate endpoints for external client vs internal zones/
# require different auth for each 
# and restrict who can update what.
 
@app.route("/zone/<string:zonename>/sensors", methods=['POST'])
def update_sensors(zonename:str):
    """
    Update a zone with UpdateZone. Read this zone's states. 
    Register the zone if not already there
    """
    assertAuthAzZone(request)
    sns = Sensors(**request.json)
    _append_and_trim(sensors[zonename], sns) 
    return _zone_response(zonename, True)

@app.route("/zone/<string:zonename>/command", methods=['POST'])
def update_command(zonename:str):
    """
    Update a zone with UpdateZone. Read this zone's states. 
    Register the zone if not already there
    """
    assertAuthAzZone(request)
    # assumes body exists, even if it is just {}
    js = request.json
    cmd = IRCommand(**js)
    # eventually, we will store these and subsample them 
    _append_and_trim(commands[zonename], cmd) 
    return _zone_response(zonename, True)

    
@app.route("/zones", methods=['GET'])
def get_zones():
    """
    Stateless query.  Read ALL zone states, including pending commands.
    """
    assertAuthAzZone(request)
    res = {zonename: _zone_response(zonename, False) for zonename in sensors}
    return res


@app.route("/test_reset", methods=['POST'])
def test_reset():
    """
    Update the zone state for testing.
    """
    assertAuthAzZone(request)
    # assert running in container
    updates = request.json
    print(f"updates {updates}")
    if cmds := updates.get('commands'):
        commands.clear()
        commands.update(cmds)
        print(f"commands {cmds}")
    if snrs := updates.get('sensors'):
        sensors.clear()
        sensors.update(snrs)
        print(f"sensors {snrs}")
    print(f"Updated to\nsensors {sensors}\ncommands {commands}")
    return '"ok"'



if __name__ == "__main__":
    # LOG starting / port
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
