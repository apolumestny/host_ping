# -*- coding: utf-8 -*-
from __future__ import annotations
import configparser
import datetime as dt
import json
import os
import subprocess
import sys

import requests

from typing import List, Union


basedir: str = os.path.dirname(os.path.abspath(__file__))
config = configparser.ConfigParser()
config_file: str = os.path.join(basedir, 'conf.ini')
if os.path.isfile(config_file):
    config.read(config_file)
else:
    # return error and print config strucrure
    print(f'Please create conf.ini in {basedir}')


class Alarm:

    def __init__(self, call_url: str, sms_url: str, sms_user: str, sms_password: str, msisdn_to_notify: List[str],
                 notification_delay: float, call_count: int,  *args, **kwargs):
        self.call_url = call_url
        self.sms_url = sms_url
        self.sms_user = sms_user
        self.sms_password = sms_password
        self.msisdn_to_notify = msisdn_to_notify
        self.notification_delay = notification_delay
        self.call_count = call_count
        self.location: dict = {'89.31.240.234': 1,
                               '185.61.131.190': 2,
                               '203.189.26.234': 3}
        super().__init__()

    def send_call_alarm(self, host: str) -> None:
        location = self.location.get(host, None)
        for msisdn in self.msisdn_to_notify:
            if location is None:
                options = f'&number={msisdn}'
                requests.get(f'{self.call_url}{options}')
            else:
                options = f'&number={msisdn}&host={location}'
                requests.get(f'{self.call_url}{options}')

    def send_sms_alarm(self, host: str) -> None:
        for msisdn in self.msisdn_to_notify:
            url = self.sms_url.format(self.sms_user, self.sms_password, msisdn, f'Host {host} become unreachable')
            requests.post(url)


class DB(Alarm):

    def __init__(self, hosts: List[str], msisdn_to_notify: List[str],
                 notification_delay: float, call_count: int, call_url: str, sms_urlm: str, *args, **kwargs) -> None:
        self.db: str = os.path.join(basedir, 'state.txt')
        if not os.path.isfile(self.db):
            # create new db file
            tmp_db: dict = dict()
            for host in hosts:
                tmp_db[host] = {'current_state': 0}
            with open(self.db, 'w') as f:
                json.dump(tmp_db, f, indent=4)
        else:
            # db already exists. need to check host from conf
            compare_host = self.compare_host_from_db_and_config(hosts)
            if compare_host['add_host'] is not None:
                for new_host in compare_host['add_host']:
                    self.add_host(new_host)
            if compare_host['delete_host'] is not None:
                for delete_host in compare_host['delete_host']:
                    self.delete_host(delete_host)
        super().__init__(msisdn_to_notify=msisdn_to_notify, notification_delay=notification_delay, call_count=call_count,
                         call_url=call_url, sms_url=sms_urlm, sms_user=sms_user, sms_password=sms_password)

    def read_db(self) -> dict:
        with open(self.db, 'r') as f:
            json_db: dict = json.load(f)
        return json_db

    def save_db(self, json_db: dict) -> None:
        with open(self.db, 'w') as f:
            json.dump(json_db, f, indent=4, default=str)

    def get_value(self, host: str, keys: List[str]) -> dict:
        # get list of keys and try to find thear value id db
        # if key don't exists return None
        resp: dict = {value: self.read_db()[host].get(value, None) for value in keys}
        return resp

    def compare_host_from_db_and_config(self, hosts: list) -> dict:
        # return difference between list of host in existing db and hosts from parameter
        existing_host: set = set(host for host in self.read_db().keys())
        host: set = set(host for host in hosts)
        new_host: set = set(host - existing_host)
        host_for_delete: set = set(existing_host - host)
        return {'add_host': new_host, 'delete_host': host_for_delete}

    def add_host(self, host: str) -> Union[None, str]:
        db = self.read_db()
        if host in db:
            return f'{host} already exist'
        db[host] = {'current_state': 0}
        self.save_db(db)
        return None

    def delete_host(self, host: str) -> Union[None, str]:
        db = self.read_db()
        if host in db:
            db.pop(host)
            self.save_db(db)
            return None
        return f'there is not {host} in db'

    def change_db_parameter(self, host: str, **kwargs) -> None:
        db: dict = self.read_db()
        for key in kwargs.keys():
            db[host][key] = kwargs[key]
        self.save_db(db)

    def notification_delay_check(self, notification_last_time: dt.datetime) -> bool:
        notification_delay: float = (dt.datetime.now() - notification_last_time).seconds / 60
        if notification_delay >= self.notification_delay:
            return True
        return False

    def check_ping_result(self, ping_result: dict) -> None:
        date_format: str = '%Y-%m-%d %H:%M:%S.%f'
        current_time: dt.datetime = dt.datetime.now()
        for host, value in ping_result.items():
            info: dict = self.get_value(host, keys=['current_state', 'call_count', 'notification_last_time', ])
            # if ping result equal 1 then host is unreachable
            # new alarm
            if value == 1 and info['current_state'] == 0:
                # self.send_call_alarm(host)
                # self.change_db_parameter(host, current_state=1, call_count=1,
                #                          notification_last_time=current_time, check_time=current_time)
                self.change_db_parameter(host, current_state=1, check_time=current_time)
                continue
            if value == 1 and info['current_state'] == 1:
                self.send_call_alarm(host)
                # self.change_db_parameter(host, current_state=1, call_count=1,
                #                          notification_last_time=current_time, check_time=current_time)
                self.change_db_parameter(host, current_state=1, unavailable=1,
                                         notification_last_time=current_time, check_time=current_time)
                continue
            # host was unreachable
            elif value == 1 and info['unavailable'] == 1:
                notification_last_time: dt.datetime = dt.datetime.strptime(info['notification_last_time'], date_format)
                # check call count if it not equal count in conf
                # and call_delay more than in conf than make call
                if info['call_count'] < self.call_count and self.notification_delay_check(notification_last_time):
                    self.send_call_alarm(host)
                    self.change_db_parameter(host,
                                             current_state=1,
                                             call_count=info['call_count'] + 1,
                                             notification_last_time=current_time,
                                             check_time=current_time,
                                             unavailable=1)

                # if call count equal count in conf than check sms_last_time
                # and if it None send sms if not None - get sms_delay if it equal or
                # more than sms_delay from conf than send sms
                elif info['call_count'] == self.call_count and self.notification_delay_check(notification_last_time):
                    self.send_sms_alarm(host)
                    self.change_db_parameter(host,
                                             current_state=1,
                                             check_time=current_time,
                                             notification_last_time=current_time)
                    continue
            # if host reachable need to check state in db
            elif value == 0 and info['current_state'] == 0:
                self.change_db_parameter(host, check_time=current_time)
                continue
            elif value == 0 and info['current_state'] == 1:
                self.change_db_parameter(host,
                                         current_state=0,
                                         call_count=0,
                                         notification_last_time=None,
                                         check_time=current_time,
                                         unavailable=0)
                continue
            else:
                self.change_db_parameter(host, check_time=current_time)


class Server:

    def __init__(self, hosts: List[str]) -> None:
        self.hosts = hosts

    def ping_servers(self) -> dict:
        result: dict = {}
        for host in self.hosts:
            proc: subprocess.Popen = subprocess.Popen(['ping', '-W', '1', '-c', '1', host], stdout=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            result[host] = proc.returncode
        return result

    def fping_servers(self) -> dict:
        cmd = ['fping', '-u', '--count', '10'] + self.hosts
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = proc.stdout.decode("utf-8").strip()
        return output

    def fping_result_to_json(self, fping: tuple):
        res = fping.split('\n')
        resp = []
        for line in res:
            host, stat = line.split(':')
            sent, received, loss = stat.split(',')[0].split('=')[1].strip().split('/')
            try:
                min, avg, max = stat.split(',')[1].split('=')[1].strip().split('/')
            except IndexError:
                min, avg, max = [None, None, None]
            resp.append([dt.datetime.utcnow(),'ip_from', host.strip(), sent, received, loss.replace('%', ''), min, avg, max,])
        return json.dumps(resp, default=str)


if __name__ == '__main__':
    hosts = config['hosts']['hosts'].split(',')
    msisdn = config['notification']['msisdn_to_notif'].split(',')
    call_count = int(config['notification']['call_count'])
    notification_delay = int(config['notification']['notification_delay'])
    call_url = config['notification']['call_url']
    sms_url = config['notification']['sms_url']
    sms_user = config['notification']['sms_username']
    sms_password = config['notification']['sms_password']

    db = DB(hosts=hosts, call_count=call_count, notification_delay=notification_delay,
            msisdn_to_notify=msisdn, call_url=call_url, sms_urlm=sms_url, sms_user=sms_user, sms_password=sms_password)

    server = Server(hosts)
    # you can check logic of alarm by edit result var
    # result = {'host_ip': state[0 - all good, 1 host unavailable]}
    result = {'9.19.19.19': 1}
    #result = server.ping_servers()
    #print(server.fping_result_to_json(result))
    db.check_ping_result(result)
