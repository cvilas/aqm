# aqm

Air Quality Monitor

## Components

- Sensirion SEN66 air quality monitor: [[info](https://sensirion.com/products/catalog/SEN66)] [[code](https://github.com/Sensirion/raspberry-pi-i2c-sen66)]
- Waveshare 2.13" 250x122 e-ink display: [[info](https://www.waveshare.com/wiki/2.13inch_e-Paper_HAT_(B))] [[code](https://github.com/waveshareteam/e-Paper)]
- Waveshare UPS HAT for Pi Zero: [[info](https://www.waveshare.com/wiki/UPS_HAT_(C))]
- Raspberry Pi Zero 2 W: [[info](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)]

## TODO

- [ ] Vendor sen66 code so we can update to new releases
- [ ] Understand why outputs from minimal-example and example-usage are different for voc and nox indices
- [ ] Understand why the nox index does not change
- [ ] Integrate sources properly
  - [ ] sen66
  - [ ] display
  - [ ] ups
- [ ] Design physical layout of components, following sen66 app notes
- [ ] Design display layout
- [ ] Design/buy project box to house all the electronics
