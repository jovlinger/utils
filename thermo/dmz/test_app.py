from unittest import TestCase

from app import app

class DMZTest(TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_update_backendz1(self):
        with app.test_client() as c:
            # now accumulate some traffic
            res = c.post('/zone/z1/command', json={'lolidk': 'what'})
            res = c.post('/zone/z1/sensors', json={'temp_centigrade': 11.45})
            res = c.post('/zone/z2/sensors', 
                         json={'temp_centigrade': 21.34, 'humid_percent': 99.99 })
            res = c.post('/zone/z1/command', json={'lolidk': 'make it so'})
            js12 = res.get_json()
            res = c.post('/zone/z3/command', json={'lolidk': 'who'})

            # now we have something to read
            res = c.post('/zone/z1/sensors', 
                         json={ 'temp_centigrade': 13.34 })
            js13 = res.get_json()
            
            self.assertNotEqual(js12['command']['last_access_dt'], js13['command']['last_access_dt'],
                                "Expected access times to be updated on /zone/ endpoint")

            self.assertEqual('make it so', js13['command']['lolidk'], 
                             "expected most recent command for zone")
            self.assertEqual(13.34, js13['sensors']['temp_centigrade'], 
                             "expected most recent sensor for zone")

            # now we have something to read
            res = c.get('/zones')
            js = res.get_json()
            print(f"js : {js}")
            self.assertEqual(['z1', 'z2', 'z3'], sorted(js.keys()))
            self.assertEqual(js13, js['z1']) # including access times
            
