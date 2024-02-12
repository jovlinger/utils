from unittest import TestCase

from app import app

class DMZTest(TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def post_200(self, c, url, json) -> "Json":
        res = c.post(url, json=json)
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def get_200(self, c, url) -> "Json":
        res = c.get(url)
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def test_update_backendz1(self):
        with app.test_client() as c:
            # now accumulate some traffic
            self.post_200(c, '/zone/z1/command', json={'lolidk': 'what'})
            self.post_200(c, '/zone/z1/sensors', json={'temp_centigrade': 11.45})
            self.post_200(c, '/zone/z2/sensors', 
                         json={'temp_centigrade': 21.34, 'humid_percent': 99.99 })
            js12 = self.post_200(c, '/zone/z1/command', json={'lolidk': 'make it so'})
            self.post_200(c, '/zone/z3/command', json={'lolidk': 'who'})

            # now we have something to read
            js13 = self.post_200(c, '/zone/z1/sensors', 
                         json={ 'temp_centigrade': 13.34 })
            
            self.assertNotEqual(js12['command']['last_access_dt'], js13['command']['last_access_dt'],
                                "Expected access times to be updated on /zone/ endpoint")

            self.assertEqual('make it so', js13['command']['lolidk'], 
                             "expected most recent command for zone")
            self.assertEqual(13.34, js13['sensors']['temp_centigrade'], 
                             "expected most recent sensor for zone")

            # now we have something to read
            js = self.get_200(c, '/zones')
            print(f"js : {js}")
            self.assertEqual(['z1', 'z2', 'z3'], sorted(js.keys()))
            self.assertEqual(js13, js['z1']) # including access times
            

    def test_update_backendz1_something_then_clear(self):
        with app.test_client() as c:
            res = c.post('/zone/z1/command', json={'lolidk': 'what'})
            res = c.post('/zone/z1/command', json={})
            res = c.post('/zone/z1/command', json=None)
