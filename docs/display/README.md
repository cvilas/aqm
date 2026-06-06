# README.md

- Enable SPI interface in Raspberry Pi
  ```bash
  sudo raspi-config
  # Choose Interfacing Options -> SPI -> yes
  ```
- Reboot
- Install tools
  ```bash
  sudo apt install python3-smbus python3-pip python3-pil python3-numpy python3-gpiozero python3-spidev python3-setuptools
  sudo apt install gpiod libgpiod-dev
  ```
- Run demo app
  ```bash
  python3 ./RaspberryPi_JetsonNano/python/examples/epd_2in13b_V4_test.py
  ```
