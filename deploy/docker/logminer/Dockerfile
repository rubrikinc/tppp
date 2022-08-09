FROM python:3.9-slim-buster
COPY logminer /logminer
RUN pip3 install -r logminer/requirements.txt

#Setting up populate-db cron
RUN apt-get update && apt-get -y install cron
COPY logminer/populate_db/populate-db-cron /etc/cron.d/populate-db-cron
RUN chmod 0644 /etc/cron.d/populate-db-cron
RUN crontab /etc/cron.d/populate-db-cron
RUN touch /var/log/cron.log
CMD cron && tail -f /var/log/cron.log
