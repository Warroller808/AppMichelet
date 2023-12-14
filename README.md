## Initial setup

- ```sudo apt update && sudo apt upgrade```

- Clone the wanted branch of this repository:
```
sudo git clone -b BRANCH_NAME url
```

## Install the app from scratch

```
cd /var/www/AppMichelet
chown -R ubuntu:www-data .
chmod +x install_app
sudo ./install_app
```
