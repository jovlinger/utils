"""
This lives on the WWW.

Accept backend long-poll connections from trusted zone. (with trust token)

Accept request; redirect to google auth, if success push to backend long poll

Backend will return result in next query, with association ID. 

Long-term, make the backend connection into a TCP based queue (connection is awkward bit)
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, Union, Optional

from flask import Flask, request, send_from_directory
from pydantic import BaseModel

JSON = Union[Dict, str, int]

class BackendRequest(BaseModel):
    security_token: str
    zone_name: str
    threading_id: str
    payload: JSON
    
class BackendReply(BaseModel):
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
    lolidk: str
    created_dt: str = ""
    last_access_dt: str = "" 

    def model_post_init(self, __context) -> None:
        if not self.created_dt:
            self.created_dt = datetime.now().isoformat()

    def model_mark_accessed(self) -> None:
        self.last_access_dt = datetime.now().isoformat()

class UpdateBackend(BaseModel):
    command: Optional[IRCommand] = None
    sensors: Optional[Sensors] = None

app = Flask(__name__) 

def assertAuthAzBackend(req):
    # skip auth for now, but let's treat house info as 'sensitive', later. 
    assert req

commands = defaultdict(list) # {zonename -> [IRCommand]}
sensors = defaultdict(list) # {zonename -> [ Sensors]}

def _lastor(lst, default=None):
    if not lst: return default
    return lst[-1]

def _backend_response(zonename, update_access) -> JSON:
    """Craft the json for one zone's response"""
    # which happens to be exactly the UpdateBackend model
    cmd = _lastor(commands[zonename])
    sns = _lastor(sensors[zonename])
    if cmd and update_access:
        cmd.model_mark_accessed()
    return UpdateBackend(command = cmd, sensors= sns).model_dump()

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
 
@app.route("/backend/<string:zonename>", methods=['POST'])
def update_backends(zonename:str):
    """
    Update a zone with UpdateBackend. Read this zone's states. 
    Register the zone if not already there
    """
    assertAuthAzBackend(request)
    ub = UpdateBackend(**request.json)
    if cmd := ub.command:
        # eventually, we will store these and subsample them 
        _append_and_trim(commands[zonename], cmd) 
    if sen := ub.sensors:
        _append_and_trim(sensors[zonename], sen) 
    return _backend_response(zonename, True)

    
@app.route("/backends", methods=['GET'])
def get_backends():
    """
    Stateless query.  Read ALL backend states, including pending commands.
    """
    assertAuthAzBackend(request)
    res = {zonename: _backend_response(zonename, False) for zonename in sensors}
    return res
