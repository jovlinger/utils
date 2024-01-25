# common entry point, invoked by container, per Dockerfile

hostname
whoami

echo env is "${ENV:-idk}"

python app.py
