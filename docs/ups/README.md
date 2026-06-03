
# README

- Enable i2c interface in Raspberry Pi
  ```bash
  sudo raspi-config
  # Choose Interfacing Options -> I2C -> yes
  ```
- Reboot
- Install tools
  ```bash
  sudo apt install i2c-tools python3-smbus
  ```
- Run demo app
  ```bash
  python3 demo.py
  ```
