# -*- coding: utf-8 -*-
###################################################################################
#
#    This program is free software: you can modify
#    it under the terms of the GNU Affero General Public License (AGPL) as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################
import pytz
import sys
from datetime import datetime
import logging
import binascii
import os
import platform
import subprocess
import time

from odoo import api, fields, models
from odoo import _
from odoo.exceptions import UserError, ValidationError
_logger = logging.getLogger(__name__)
try:
    from zk import ZK, const
except ImportError:
    _logger.error("Unable to import pyzk library. Try 'pip3 install pyzk'.")

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    device_id = fields.Char(string='Biometric Device ID')


class ZkMachine(models.Model):
    _name = 'zk.machine'
    
    name = fields.Char(string='Machine IP', required=True)
    port_no = fields.Integer(string='Port No', required=True, default="4370")
    address_id = fields.Many2one('res.partner', string='Working Address')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id)
    zk_timeout = fields.Integer(string='ZK Timeout', required=True, default="120")
    zk_after_date =  fields.Datetime(string='Attend Start Date', help='If provided, Attendance module will ignore records before this date.')

    @api.multi
    def device_connect(self, zkobj):
        try:
            conn =  zkobj.connect()
            return conn
        except:
            _logger.info("zk.exception.ZKNetworkError: can't reach device.")
            raise UserError("Connection To Device cannot be established.")
            return False

    # @api.multi
    # def device_connect(self, zkobj):
    #     for i in range(10):
    #         try:
    #             conn =  zkobj.connect()
    #             return conn
    #         except:
    #             _logger.info("zk.exception.ZKNetworkError: can't reach device.")
    #             conn = False
    #     return False


    @api.multi
    def try_connection(self):
        for r in self:
            machine_ip = r.name
            if platform.system() == 'Linux':
                response = os.system("ping -c 1 " + machine_ip)
                if response == 0:
                    raise UserError("Biometric Device is Up/Reachable.")
                else:
                    raise UserError("Biometric Device is Down/Unreachable.") 
            else:
                prog = subprocess.run(["ping", machine_ip], stdout=subprocess.PIPE)
                if 'unreachable' in str(prog):
                    raise UserError("Biometric Device is Down/Unreachable.")
                else:
                    raise UserError("Biometric Device is Up/Reachable.")  
    
    @api.multi
    def clear_attendance(self):
        for info in self:
            try:
                machine_ip = info.name
                zk_port = info.port_no
                timeout = info.zk_timeout
                try:
                    zk = ZK(machine_ip, port = zk_port , timeout=timeout, password=0, force_udp=False, ommit_ping=False)
                except NameError:
                    raise UserError(_("Pyzk module not Found. Please install it with 'pip3 install pyzk'."))                
                conn = self.device_connect(zk)
                if conn:
                    conn.enable_device()
                    clear_data = zk.get_attendance()
                    if clear_data:
                        #conn.clear_attendance()
                        self._cr.execute("""delete from zk_machine_attendance""")
                        conn.disconnect()
                        raise UserError(_('Attendance Records Deleted.'))
                    else:
                        raise UserError(_('Unable to clear Attendance log. Are you sure attendance log is not empty.'))
                else:
                    raise UserError(_('Unable to connect to Attendance Device. Please use Test Connection button to verify.'))
            except:
                raise ValidationError('Unable to clear Attendance log. Are you sure attendance device is connected & record is not empty.')

    def zkgetuser(self, zk):
        try:
            users = zk.get_users()
            print(users)
            return users
        except:
            raise UserError(_('Unable to get Users.'))

    @api.model
    def cron_download(self):
        machines = self.env['zk.machine'].search([])
        for machine in machines :
            machine.download_attendance()
        
    @api.multi
    def download_attendance(self):
        _logger.info("++++++++++++Cron Executed++++++++++++++++++++++")
        zk_attendance = self.env['zk.machine.attendance']
        att_obj = self.env['hr.attendance']
        for info in self:
            machine_ip = info.name
            zk_port = info.port_no
            timeout = info.zk_timeout
            try:
                zk = ZK(machine_ip, port = zk_port , timeout=timeout, password=0, force_udp=False, ommit_ping=False)
            except NameError:
                raise UserError(_("Pyzk module not Found. Please install it with 'pip3 install pyzk'."))
            conn = self.device_connect(zk)
            if conn:
                # conn.disable_device() #Device Cannot be used during this time.
                try:
                    user = conn.get_users()
                except:
                    user = False
                try:
                    attendance = conn.get_attendance()
                except:
                    attendance = False
                if attendance:
                    for each in attendance:
                        atten_time = each.timestamp
                        atten_time = datetime.strptime(atten_time.strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S')
                        if info.zk_after_date == False:
                            tmp_zk_after_date = datetime.strptime('2000-01-01',"%Y-%m-%d")
                        else:
                            tmp_zk_after_date = datetime.strptime(info.zk_after_date,'%Y-%m-%d %H:%M:%S')
                        if atten_time != False and atten_time > tmp_zk_after_date:
                            local_tz = pytz.timezone(
                                self.env.user.partner_id.tz or 'GMT')
                            local_dt = local_tz.localize(atten_time, is_dst=None)
                            utc_dt = local_dt.astimezone(pytz.utc)
                            utc_dt = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                            atten_time = datetime.strptime(
                                utc_dt, "%Y-%m-%d %H:%M:%S")
                            tmp_utc = local_dt.astimezone(pytz.utc)
                            tmp_attend = tmp_utc.strftime("%m-%d-%Y %H:%M:%S")
                            atten_time = fields.Datetime.to_string(atten_time)
                            if user:
                                for uid in user:
                                    if uid.user_id == each.user_id:
                                        get_user_id = self.env['hr.employee'].search(
                                            [('device_id', '=', each.user_id)])
                                        if get_user_id:
                                            duplicate_atten_ids = zk_attendance.search(
                                                [('device_id', '=', each.user_id), ('punching_time', '=', atten_time)])
                                            if duplicate_atten_ids:
                                                continue
                                            else:
                                                zk_attendance.create({'employee_id': get_user_id.id,
                                                                    'device_id': each.user_id,
                                                                    'attendance_type': str(each.status),
                                                                    'punch_type': str(each.punch),
                                                                    'punching_time': atten_time,
                                                                    'address_id': info.address_id.id})
                                                att_var = att_obj.search([('employee_id', '=', get_user_id.id),
                                                                        ('check_out', '=', False)])
                                                if each.punch == 0: #check-in
                                                    if not att_var:
                                                        attend_rec_tmp = att_obj.search([('employee_id', '=', get_user_id.id),('check_out', '>', tmp_attend)])
                                                        if not attend_rec_tmp:
                                                            att_obj.create({'employee_id': get_user_id.id,
                                                                            'check_in': atten_time})

                                                if each.punch == 1: #check-out
                                                    if len(att_var) == 1:
                                                        att_var.write({'check_out': atten_time})
                                                    else:
                                                        att_var1 = att_obj.search([('employee_id', '=', get_user_id.id)])
                                                        if att_var1:
                                                            att_var1[-1].write({'check_out': atten_time})

                                        else:
                                            pass
                                    else:
                                        pass
                    # conn.enable_device() #Enable Device Once Done.
                    conn.disconnect
                    return True
                else:
                    raise UserError(_('No attendances found in Attendance Device to Download.'))
                    # conn.enable_device() #Enable Device Once Done.
                    conn.disconnect
            else:
                raise UserError(_('Unable to connect to Attendance Device. Please use Test Connection button to verify.'))

