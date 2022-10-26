import datetime
import imp
import importlib
import json
import os
import shlex
import sys
import subprocess
# import local_config
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QIntValidator, QRegExpValidator
from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton
from functools import partial
from multiprocessing.pool import Pool
from queue import Queue



config_template = '''# ERPNext related configs
ERPNEXT_API_KEY = '{0}'
ERPNEXT_API_SECRET = '{1}'
ERPNEXT_URL = '{2}'


# operational configs
PULL_FREQUENCY = {3} or 60 # in minutes
LOGS_DIRECTORY = 'logs' # logs of this script is stored in this directory
IMPORT_START_DATE = '{4}' or None # format: '20190501'

# Biometric device configs (all keys mandatory)
    #- device_id - must be unique, strictly alphanumerical chars only. no space allowed.
    #- ip - device IP Address
    #- punch_direction - 'IN'/'OUT'/'AUTO'/None
    #- clear_from_device_on_fetch: if set to true then attendance is deleted after fetch is successful.
    #(Caution: this feature can lead to data loss if used carelessly.)
devices = {5}

'''

class BiometricWindow(QMainWindow):
    queue = Queue()
    def __init__(self):
        super().__init__()
        self.reg_exp_for_ip = r"((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?=\s*netmask)"
        self.init_ui()

    def closeEvent(self, event):
        can_exit = not hasattr(self, "p")
        if can_exit:
            event.accept()
        else:
            create_message_box(text="Window cannot be closed when \nservice is running!", title="Message", width=200)
            event.ignore()

    def init_ui(self):
        self.counter = 0
        self.setup_window()
        self.setup_textboxes_and_label()
        self.center()
        self.show()

    def setup_window(self):
        self.setFixedSize(470, 550)
        self.setWindowTitle('ERPNext Biometric Service')

    def setup_textboxes_and_label(self):

        self.create_label("API Secret", "api_secret", 20, 0, 200, 30)
        self.create_field("textbox_erpnext_api_secret", 20, 30, 200, 30)

        self.create_label("API Key", "api_key", 20, 60, 200, 30)
        self.create_field("textbox_erpnext_api_key", 20, 90, 200, 30)

        self.create_label("ERPNext URL", "erpnext_url", 20, 120, 200, 30)
        self.create_field("textbox_erpnext_url", 20, 150, 200, 30)

        self.create_label("Pull Frequency (in minutes)",
                          "pull_frequency", 250, 0, 200, 30)
        self.create_field("textbox_pull_frequency", 250, 30, 200, 30)

        self.create_label("Import Start Date",
                          "import_start_date", 250, 60, 200, 30)
        self.create_field("textbox_import_start_date", 250, 90, 200, 30)
        self.validate_data(r"^\d{1,2}/\d{1,2}/\d{4}$", "textbox_import_start_date")
        
        self.create_separator(210, 470)
        self.create_button('+', 'add', 390, 230, 35, 30, self.add_devices_fields)
        self.create_button('-', 'remove', 420, 230, 35, 30, self.remove_devices_fields)

        self.create_label("Device ID", "device_id", 20, 260, 0, 30)
        self.create_label("Device IP", "device_ip", 170, 260, 0, 30)
        self.create_label("Password", "password", 320, 260, 0, 0)

        # First Row for table
        self.create_field("device_id_0", 20, 290, 145, 30)
        self.create_field("device_ip_0", 165, 290, 145, 30)
        self.validate_data(self.reg_exp_for_ip, "device_ip_0")
        self.create_field("password_0", 310, 290, 145, 30)

        # Actions buttons
        self.create_button('Set Configuration', 'set_conf', 20, 500, 130, 30, self.setup_local_config)
        self.create_button('Start Service', 'start_or_stop_service', 320, 500, 130, 30, self.integrate_biometric, enable=False)
        self.create_button('Running Status', 'running_status', 170, 500, 130, 30, self.get_running_status, enable=False)
        self.set_default_value_or_placeholder_of_field()

        # validating integer
        self.onlyInt = QIntValidator(10, 30)
        self.textbox_pull_frequency.setValidator(self.onlyInt)

    def set_default_value_or_placeholder_of_field(self):
        if os.path.exists("local_config.py"):
            import json
            # Opening JSON file
            with open('../local_config.json', 'r') as openfile:

                # Reading from json file
                json_object = json.load(openfile)
            self.textbox_erpnext_api_secret.setText(json_object.get('ERPNEXT_API_SECRET'))
            self.textbox_erpnext_api_key.setText(json_object.get('ERPNEXT_API_KEY'))
            self.textbox_erpnext_url.setText(json_object.get('ERPNEXT_URL'))
            self.textbox_pull_frequency.setText(str(json_object.get('PULL_FREQUENCY')))

            if len(json_object.get('devices')):
                self.device_id_0.setText(json_object.get('devices')[0].get('device_id'))
                self.device_ip_0.setText(json_object.get('devices')[0].get('ip'))
                self.password_0.setText(json_object.get('devices')[0].get('password'))

            if len(json_object.get('devices')) > 1:
                for _ in range(self.counter, len(json_object.get('devices')) - 1):
                    self.add_devices_fields()

                    device = getattr(self, 'device_id_' + str(self.counter))
                    ip = getattr(self, 'device_ip_' + str(self.counter))
                    password = getattr(self, 'password_' + str(self.counter))

                    device.setText(json_object.get('devices')[self.counter].get('device_id'))
                    ip.setText(json_object.get('devices')[self.counter].get('ip'))
                    password.setText(json_object.get('devices')[self.counter].get('password'))
        else:
            self.textbox_erpnext_api_secret.setPlaceholderText("c70ee57c7b3124c")
            self.textbox_erpnext_api_key.setPlaceholderText("fb37y8fd4uh8ac")
            self.textbox_erpnext_url.setPlaceholderText("example.erpnext.com")
            self.textbox_pull_frequency.setPlaceholderText("60")

        self.textbox_import_start_date.setPlaceholderText("DD/MM/YYYY")

    # Widgets Genrators
    def create_label(self, label_text, label_name, x, y, height, width):
        setattr(self,  label_name, QLabel(self))
        label = getattr(self, label_name)
        label.move(x, y)
        label.setText(label_text)
        if height and width:
            label.resize(height, width)
        label.show()

    def create_field(self, field_name, x, y, height, width):
        setattr(self,  field_name, QLineEdit(self))
        field = getattr(self, field_name)
        field.move(x, y)
        field.resize(height, width)
        field.show()

    def create_separator(self, y, width):
        setattr(self, 'separator', QLineEdit(self))
        field = getattr(self, 'separator')
        field.move(0, y)
        field.resize(width, 5)
        field.setEnabled(False)
        field.show()

    def create_button(self, button_label, button_name, x, y, height, width, callback_function, enable=True):
        setattr(self,  button_name, QPushButton(button_label, self))
        button = getattr(self, button_name)
        button.move(x, y)
        button.resize(height, width)
        button.clicked.connect(callback_function)
        button.setEnabled(enable)

    def center(self):
        frame = self.frameGeometry()
        screen = QApplication.desktop().screenNumber(QApplication.desktop().cursor().pos())
        centerPoint = QApplication.desktop().screenGeometry(screen).center()
        frame.moveCenter(centerPoint)
        self.move(frame.topLeft())

    def add_devices_fields(self):
        if self.counter < 5:
            self.counter += 1
            self.create_field("device_id_" + str(self.counter), 20, 290+(self.counter * 30), 145, 30)
            self.create_field("device_ip_" + str(self.counter), 165, 290+(self.counter * 30), 145, 30)
            self.validate_data(self.reg_exp_for_ip, "device_ip_" + str(self.counter))
            self.create_field("password_" + str(self.counter), 310, 290+(self.counter * 30), 145, 30)

    def validate_data(self, reg_exp, field_name):
        field = getattr(self, field_name)
        reg_ex = QRegExp(reg_exp)
        input_validator = QRegExpValidator(reg_ex, field)
        field.setValidator(input_validator)

    def remove_devices_fields(self):
        if self.counter > 0:
            b = getattr(self, "password_" + str(self.counter))
            b.deleteLater()
            b = getattr(self, "device_id_" + str(self.counter))
            b.deleteLater()
            b = getattr(self, "device_ip_" + str(self.counter))
            b.deleteLater()

            self.counter -= 1

    def integrate_biometric(self):
        button = getattr(self, "start_or_stop_service")
        if not hasattr(self, 'worker'):
            print("Starting Service...")
            from erpnext_sync import SyncService
            import json
    
            # Opening JSON file
            with open('../local_config.json', 'r') as openfile:

                # Reading from json file
                json_object = json.load(openfile)
            self.worker = SyncService(BiometricWindow.queue,(int(json_object.get('PULL_FREQUENCY')) * 60))
            # Setting daemon to True will let the main thread exit even though the workers are blocking
            self.worker.daemon = True
            self.worker.start()
            BiometricWindow.queue.join()
            
            button.setText("Stop Service")
            create_message_box("Service status", "Service has been started")
            self.create_label(str(datetime.datetime.now()), "service_start_time", 20, 60, 200, 30)
            self.service_start_time.setHidden(True)
            getattr(self, 'running_status').setEnabled(True)
        else:
            print("Stopping Service...")
            self.worker.stop_sevrice()
            del self.worker
            button.setText("Start Service")
            create_message_box("Service status", "Service has been stoped")
            getattr(self, 'running_status').setEnabled(False)

    def setup_local_config(self):
        bio_config = self.get_local_config()

        print("Setting Local Configuration...")

        if not bio_config:
            print("Local Configuration not updated...")
            return 0

        if os.path.exists("local_config.py"):
            os.remove("local_config.py")

        with open("local_config.py", 'w+') as f:
            f.write(bio_config)
            
        print("Local Configuration Updated.")

        create_message_box("Message", "Configuration Updated!\nClick on Start Service.")

        getattr(self, 'start_or_stop_service').setEnabled(True)

    def get_device_details(self):
        devices = []

        for idx in range(0, self.counter+1):
            password = getattr(self, "password_" + str(idx)).text()
            device_id = getattr(self, "device_id_" + str(idx)).text()
            devices.append({
                'device_id': device_id,
                'ip': getattr(self, "device_ip_" + str(idx)).text(),
                'password': password,
                'punch_direction': '',
                'clear_from_device_on_fetch': ''
            })
        
        return devices

    def get_local_config(self):
        if not validate_fields(self):
            return 0
        string = self.textbox_import_start_date.text()
        formated_date = "".join([ele for ele in reversed(string.split("/"))])

        devices = self.get_device_details()
        import json
        dictionary = {
            "ERPNEXT_API_KEY": self.textbox_erpnext_api_key.text(),
            "ERPNEXT_API_SECRET": self.textbox_erpnext_api_secret.text(),
            "ERPNEXT_URL": self.textbox_erpnext_url.text(),
            "PULL_FREQUENCY": self.textbox_pull_frequency.text(),
            "LOGS_DIRECTORY": 'logs',
            "IMPORT_START_DATE": formated_date,
            "devices": devices,
            "allowed_exceptions" : [1,2,3]
        }
        
        # Serializing json
        json_object = json.dumps(dictionary, indent=7)
        
        # Writing to sample.json
        with open("../local_config.json", "w") as outfile:
            outfile.write(json_object)

        return config_template.format(self.textbox_erpnext_api_key.text(), self.textbox_erpnext_api_secret.text(), self.textbox_erpnext_url.text(), self.textbox_pull_frequency.text(), formated_date, json.dumps(devices))

    def get_running_status(self):
        import json
    
        # Opening JSON file
        with open('../local_config.json', 'r') as openfile:

            # Reading from json file
            json_object = json.load(openfile)
        running_status = []
        with open('/'.join([json_object.get('LOGS_DIRECTORY')])+'/logs.log', 'r') as f:
            index = 0
            for idx, line in enumerate(f,1):
                logdate = convert_into_date(line.split(',')[0], '%Y-%m-%d %H:%M:%S')
                if logdate and logdate >= convert_into_date(self.service_start_time.text().split('.')[0] , '%Y-%m-%d %H:%M:%S'):
                    index = idx
                    break
            if index:
                running_status.extend(read_file_contents('logs',index))

        with open('/'.join([json_object.get('LOGS_DIRECTORY')])+'/error.log', 'r') as fread:
            error_index = 0
            for error_idx, error_line in enumerate(fread,1):
                start_date = convert_into_date(self.service_start_time.text().split('.')[0] , '%Y-%m-%d %H:%M:%S')
                if start_date and start_date.strftime('%Y-%m-%d') in error_line:
                    error_logdate = convert_into_date(error_line.split(',')[0], '%Y-%m-%d %H:%M:%S')
                    if error_logdate and error_logdate >= start_date:
                        error_index = error_idx
                        break
            if error_index:
                running_status.extend(read_file_contents('error',error_index))

        if running_status:
            create_message_box("Running status", ''.join(running_status))
        else:
            create_message_box("Running status", 'Process not yet started')

def read_file_contents(file_name, index):
    import json
    
    # Opening JSON file
    with open('../local_config.json', 'r') as openfile:

        # Reading from json file
        json_object = json.load(openfile)
    running_status = []
    with open('/'.join([json_object.get('LOGS_DIRECTORY')])+f'/{file_name}.log', 'r') as file_handler:
        for idx, line in enumerate(file_handler,1):
            if idx>=index:
                running_status.append(line)
    return running_status


def validate_fields(self):
    def message(text):
        create_message_box("Missing Value", "Please Set {}".format(text), "warning")

    if not self.textbox_erpnext_api_key.text():
        return message("API Key")

    if not self.textbox_erpnext_api_secret.text():
        return message("API Secret")

    if not self.textbox_erpnext_url.text():
        return message("ERPNext URL")

    if not self.textbox_import_start_date.text():
        return message("Import Start Date")

    return validate_date(self.textbox_import_start_date.text())


def validate_date(date):
    try:
        datetime.datetime.strptime(date, '%d/%m/%Y')
        return True
    except ValueError as e:
        create_message_box("", "Please Enter Date in correct format", "warning", width=200)
        return False


def convert_into_date(datestring, pattern):
    try:
        return datetime.datetime.strptime(datestring, pattern)
    except Exception as e:
        return None


def create_message_box(title, text, icon="information", width=150):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    lineCnt = len(text.split('\n'))
    if lineCnt > 15:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(1)
        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        layout = QtWidgets.QVBoxLayout(content)
        tmpLabel = QtWidgets.QLabel(text)
        tmpLabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(tmpLabel)
        msg.layout().addWidget(scroll, 12, 10, 1, msg.layout().columnCount())
        msg.setStyleSheet("QScrollArea{min-width:550 px; min-height: 400px}")
    else:
        msg.setText(text)
        if icon == "warning":
            msg.setIcon(QtWidgets.QMessageBox.Warning)
            msg.setStyleSheet("QMessageBox Warning{min-width: 50 px;}")
        else:
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setStyleSheet("QMessageBox Information{min-width: 50 px;}")
        msg.setStyleSheet("QmessageBox QLabel{min-width: "+str(width)+"px;}")
    msg.exec_()


def setup_window():
    biometric_app = QApplication(sys.argv)
    biometric_window = BiometricWindow()
    biometric_app.exec_()


if __name__ == "__main__":
    setup_window()
