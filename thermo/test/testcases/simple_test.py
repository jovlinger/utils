"""
Test driver for docker-compose

hint. After a run, do 
> docker compose logs testdriver to get the test logs.
"""

import requests

b = "http://dmz:5000/backends"
o = "http://onboard:5000"

name_supply = ["bob", "jill", "jack", "annie", "mark", "mary", "paul", "stella"]

class Zone:
    def __init__():
        # what about multiple zones?
        pass
    

    def set_fake_readings(self, temp, humid):
        r = requests.post(f"{o}/_test_readings", 
                          {'temp_centigrade': temp, 'humid_percent': humid})
        assert r.status_code == 200
        return r.json()

class External:

    def issue_command(self, zone, *, lolidk):
        r = requests.post(f"{b}/zone/{self.name}/command", {'lolidk': lolidk})
        assert r.status_code == 200
        return r.json()

    def all_backends(self):
        r = requests.get(b)
        assert r.status_code == 200
        return r.json()
        

def reset_dmz():
    r = request.post(f"{b}/_test_reset", {'commands':{}, 'sensors': {}})
    assert r.status_code == 200
    assert r.text == "ok"

def test_onboard_help():
    """Tests that we can reach onboard, and that the app is running"""
    res_o = requests.get(f"{o}/help")
    js_o = res_o.json()
    assert 'msg' in js_o
    # this is not very good, but frankly unlikely to change often
    assert 'help -> this message' in js_o['msg']

def test_dmz_backend():
    """Simple first test."""
    reset_dmz()
    
    e1 = External()
    o1 = Onboard()

    js = e1.all_backends()
    assert js == {}, f"XXX json {js} != {}"
    
    o1.set_fake_readings(12, 34)
    



