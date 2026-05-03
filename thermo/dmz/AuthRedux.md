DMZ auth Requirements and Plan
==============================

scope: ~/github.com/jovlinger/utils/thermo/dmz
goal: define requirements and plan for dmz (open-to-internet) auth

# this document

This is a live document, to be rewritten by agent during planning and execution phases to track work. 
It will not be a permanent fixture, and does not need to be targeted for human consumption. 
Keep prose minimal and precise. 

# Summary of end state (not current state)

The DMZ host exposes the following ports (Agent to add to this list as needed)

- **jovlinger.duckdns.org:22 sshd**  
  Not on by default, enabled by onboard /root/sshd.sh script. Done. 
- **jovlinger.duckdns.org:80 http -> https** 
  dmz-ui, a python flask? python script.  This port should be protected by oauth, via google IdP -> bearer/access token. 
  Access without the appropriate headers should start the Oauth flow. 
  The flow needs to be implemented; this is proabably available as a library. Not Done. 
- **jovlinger.duckdns.org:5000**
  dmz, a python flask app.  
  To be accessed by utils/thermo/twoway next to utils/thermo/onboard. 
  These are encrypted via pre-distributed public key encryption. Done. 

- **???** we also need some way for dmz-ui to speak to dmz, to read status and inject commands. 
  - unauthed local-host ports? 
  - unix domain sockets?
  - combine the two apps (dmz and dmz-ui) into one app? 

# Plan

1. first step is to verify my state above for "Done" items. 
2. decide on ???
3. research best ways to implement oauth flow. I am assuming there is a library, but maybe it is trivial? 
4. enumerate steps to implement  the goal of authenticated exposed ports on dmz.

