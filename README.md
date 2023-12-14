#!/bin/bash
set -e

if [[ $(id -u) -ne 0 ]]; then echo "Please run as root"; exit 1; fi
read -rp "db_pass: " DB_PASS
read -rp "secret_key: " SECRET_KEY
read -rp "token: " TOKEN
read -rp "replicator_pass: " REPLICATOR_PASS
read -rp "master_domain: " MASTER_DOMAIN
read -rp "master_ip: " MASTER_IP
read -rp "
Summary:
db_pass         = $DB_PASS
secret_key      = $SECRET_KEY
token           = $TOKEN
replicator_pass = $REPLICATOR_PASS
master_domain   = $MASTER_DOMAIN
master_ip       = $MASTER_IP
Confirm parameters ? (y/N)
" confirm && [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]] || exit 1

USER=$(id -un 1000)

timedatectl set-timezone Europe/Paris

sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
apt update
apt install -y postgresql-10 libpq-dev git python3-pip apache2 libapache2-mod-wsgi-py3 snapd
snap install core; sudo snap refresh core
snap install --classic certbot
ln -s /snap/bin/certbot /usr/bin/certbot

service apache2 stop

cd /var/www/FretAPI || exit

python3 -m pip install virtualenv
python3 -m virtualenv venv
source venv/bin/activate

cd /var/www/FretAPI/FretAPI || exit

pip3 install -r requirements.txt
mkdir media/ && mkdir logs/ && touch logs/main.log && chmod -R g+w logs/
echo "$DB_PASS" > db_pass.txt
echo "$SECRET_KEY" > secret_key.txt
echo "$TOKEN" > token.txt
sed -i 's/DEBUG = True/DEBUG = False/g' FretAPI/settings.py
sed -i "s/ALLOWED_HOSTS = \[.*\]/ALLOWED_HOSTS = \[\"$MASTER_IP\", \"$MASTER_DOMAIN\"\]/g" FretAPI/settings.py
python3 manage.py collectstatic
touch master

chown -R "$USER":www-data .
chmod o-r db_pass.txt secret_key.txt token.txt

su postgres -c "
psql -c \"
CREATE ROLE fretapi WITH PASSWORD '$DB_PASS' LOGIN CREATEDB;
CREATE ROLE replicator WITH PASSWORD '$REPLICATOR_PASS' REPLICATION;
\" -c \"
CREATE DATABASE fretapi_db OWNER fretapi;
\"
"

service postgresql stop

sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" /etc/postgresql/10/main/postgresql.conf
sed -i 's/#wal_level = replica/wal_level = replica/g' /etc/postgresql/10/main/postgresql.conf
sed -i 's/#wal_keep_segments = 0/wal_keep_segments = 32/g' /etc/postgresql/10/main/postgresql.conf
sed -i 's/#hot_standby = on/hot_standby = on/g' /etc/postgresql/10/main/postgresql.conf

echo "
host    fretapi_db      fretapi         0.0.0.0/0               md5
host    replication     replicator      0.0.0.0/0               md5
" >> /etc/postgresql/10/main/pg_hba.conf

crontab -l | { cat; echo "*/30 7-20 * * 1-5 /bin/bash -c 'cd /var/www/FretAPI && source venv/bin/activate && python3 backup_job.py'"; } | crontab -

echo "source /var/www/FretAPI/venv/bin/activate" >> "/home/$USER/.bashrc"
echo "
ServerName $MASTER_DOMAIN

WSGIDaemonProcess FretAPI processes=4 python-home=/var/www/FretAPI/venv python-path=/var/www/FretAPI
WSGIProcessGroup FretAPI
WSGIScriptAlias / /var/www/FretAPI/FretAPI/wsgi.py

<VirtualHost *:80>
    ErrorLog \${APACHE_LOG_DIR}/FretAPI-error.log
    CustomLog \${APACHE_LOG_DIR}/FretAPI-access.log combined

    Alias /robots.txt /var/www/FretAPI/static/robots.txt
    Alias /favicon.ico /var/www/FretAPI/static/favicon.ico
    Alias /static/ /var/www/FretAPI/static/
    Alias /media/ /var/www/FretAPI/media/

    <Directory /var/www/FretAPI/FretAPI>
        <Files wsgi.py>
            Require all granted
        </Files>
    </Directory>

    <Directory /var/www/FretAPI/static>
        Require all granted
    </Directory>

    <Directory /var/www/FretAPI/media>
        Require all granted
    </Directory>
</VirtualHost>
" > /etc/apache2/sites-available/FretAPI.conf

a2dissite 000-default.conf
a2ensite FretAPI

certbot --apache -d "$MASTER_DOMAIN"

service postgresql start
python3 manage.py makemigrations
python3 manage.py makemigrations main
python3 manage.py migrate
service apache2 start
apachectl graceful
