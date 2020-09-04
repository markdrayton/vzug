#!/usr/bin/env python3

import argparse
import json
import logging
import os
import sys
import time
import toml

import influxdb
import requests


class Appliance:
    def __init__(self, name, host):
        self.name = name
        self.url = f'http://{host}{self.PATH}'

    def parse(self, response):
        pass

    def collect(self):
        tries = 3
        while tries > 0:
            try:
                r = requests.get(self.url, timeout=2)
                logging.info(f'{self.name}: {r.text}')
                if r.status_code == 200:
                    return self.parse(r.text)
                logging.warning(f'{self.name}: got {r.status_code} from {self.url}')
            except requests.exceptions.RequestException as e:
                logging.error(f'{self.name}: exception fetching {self.url}: {e}')
            time.sleep(1)
            tries -= 1
        logging.error(f'{self.name}: failed to get {self.url}')
        return None


class Washer(Appliance):
    PATH = '/hh?command=getCommand&value=ecomXstatXtotal'

    def parse(self, response):
        data = json.loads(response)
        value = data['value']
        power, _, water = data['value'].partition(', ')
        return {
            # sometimes it's 2.5 kWh, sometimes it's 2,5 kWh ..
            'power': float(power.split(' ')[1].replace(',', '.')),
            'water': int(water.split(' ')[1][:-1]),
        }


class Dryer(Appliance):
    PATH = '/hh?command=getTotalXconsumptionXdrumDry'

    def parse(self, response):
        return {
            'power': float(response.split(' ')[0]),
        }


class Oven(Appliance):
    PATH = '/hh?command=getTotalXconsumption'

    def parse(self, response):
        return {
            'power': float(response.split(' ')[0]),
        }


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)-15s %(levelname)s %(filename)s:%(lineno)d %(message)s',
)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('-c', '--config-file', default='config.toml')
    return ap.parse_args()


def instantiate(cls, data):
    return getattr(sys.modules[__name__], cls)(data['name'], data['host'])


def main():
    args = parse_args()

    config = toml.load(open(args.config_file))
    appliances = [instantiate(cls, data) for cls, data in config['appliances'].items()]

    start = time.time()

    while True:
        ts = time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())

        points = []
        for a in appliances:
            fields = a.collect()
            if not fields:
                continue
            points.append({
                "measurement": "appliances",
                "tags": {
                    "name": a.name,
                },
                "time": ts,
                "fields": fields,
            })
        logging.info(points)

        client = influxdb.InfluxDBClient(
            config['database']['host'],
            config['database']['port'],
            config['database']['user'],
            config['database']['pass'],
            config['database']['name'],
        )
        
        try:
            if not client.write_points(points):
                logging.error('failed to write points!')
        except Exception as e:
            logging.error(f'exception while writing points: {e}')

        time.sleep(60.0 - ((time.time() - start) % 60.0))

if __name__ == '__main__':
    main()
