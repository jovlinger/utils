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
            res = c.post('/backend/z3', json={})
            js0 = res.get_json()
            self.assertIsNone(js0['command'], "expected to handle empty data gracefully")
            
            # now accumulate some traffic
            res = c.post('/backend/z1', 
                         json={
                             'command': {'lolidk': 'what'},
                             'sensors': {'temp_centigrade': 11.45}
                         })
            res = c.post('/backend/z2', 
                         json={
                             'sensors': {'temp_centigrade': 21.34, 'humid_percent': 99.99 }
                         })
            res = c.post('/backend/z1', 
                         json={
                             'command': {'lolidk': 'make it so' }
                         })
            js12 = res.get_json()

            # now we have something to read
            res = c.post('/backend/z1', 
                         json={
                             'sensors': {'temp_centigrade': 13.34 }
                         })
            js13 = res.get_json()
            
            self.assertNotEqual(js12['command']['last_access_dt'], js13['command']['last_access_dt'],
                                "Expected access times to be updated on /backend/ endpoint")

            self.assertEqual('make it so', js13['command']['lolidk'], 
                             "expected most recent command for zone")
            self.assertEqual(13.34, js13['sensors']['temp_centigrade'], 
                             "expected most recent sensor for zone")

            # now we have something to read
            res = c.get('/backends')
            js = res.get_json()
            print(f"js : {js}")
            self.assertEqual(['z1', 'z2', 'z3'], sorted(js.keys()))
            self.assertEqual(js13, js['z1']) # including access times
            
