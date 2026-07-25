# Air quality monitor - design guideline

## Components

- Sensirion SEN66 air quality monitor: [[info](https://sensirion.com/products/catalog/SEN66)] [[code](https://github.com/Sensirion/raspberry-pi-i2c-sen66)]
- Waveshare UPS HAT for Pi Zero: [[info](https://www.waveshare.com/wiki/UPS_HAT_(C))]
- Raspberry Pi Zero 2 W: [[info](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)]

## Design considerations

- Allowed programming languages: python, typescript, rust, C++. Use idiomatic constructs
- Report CO2, VOC, temperature, humidity, PM1, PM2.5, PM4, PM10 every second
- UX
  - User directly connects to web service running on the pi via their browser
  - Browser shows 2D graph for all measured parameters, along with a readout of current value clearly
  - Graph segments colorised as green, yellow, orange, red to show severity of pollution