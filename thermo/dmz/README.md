DMZ is the part of the application which handles access to the internet at large.

As such, it has zero credentials, functioning only as an intermediate scratch-pad 
for rendezvous between the two parties: the Zones, and the Controller. 

The way it works is 
1. The interior zones (one RPi+ANAVI hat per zone), POST their state to an endpoint. 
   In reply, they receive the most recent command for that zone (along with when it was). 

2. The (eventually) 3rd party authed client aslo posts commands for each zone, 
   and in reply gets the most recent state. 
   
3. (for now, the same object with a command slot and sensor slot is used for both, which means that the
   the zones can post their own commmands and the client can spoof temp settings. Easy to fix)

