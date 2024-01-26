# common entry point, invoked by container, per Dockerfile

hostname
whoami

python twoway.py "http://onboard/environment" "http://dmz/zone/zoneyzone/sensors" "http://onboard/daikin" &

python app.py
