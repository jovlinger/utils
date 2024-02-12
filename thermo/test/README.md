Testing microservices
=====================

**The Main thesis / TL;DR**

It is hard to meaningfully test a microservice in isolation because it is tightly integrated into 
an ecosystem. Thus all local tests become unit-tests. 

To get more meaningful tests, we wire together several micro-services into a black-box group, and assert
against observable state. For tests we might also expose internal state via a test-only API, or 
peek into the database

# Testing Thermo

**NB how all all of these are in the future tense**

To avoid needing access to real sensors, we will use a testing API to
inject fake measurements into `thermo`.

To speed up tests, the pingpong application will be started with 10 ms
wait. This is fast enough to let tests run quickly, and slow enough
not to overload the machine.

The main test target will be `dmz`, as it is the publically visible
part of the application.

# and some canned commands

- run tests:
> make dockertest

- copy file from container (doesn't have to be running)
> docker cp f1c711b7e058:/app/twoway.out -

- log into stopped container (that is: run bash interactively)
> docker start  f1c711b7e058
> docker exec -it f1c711b7e058 bash 

- 