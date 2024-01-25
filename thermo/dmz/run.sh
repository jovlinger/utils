# common entry point, invoked by container, per Dockerfile

hostname
whoami

echo dmz ENV "${ENV:-idk}"

python app.py
