import requests
from datetime import datetime
from random import randint
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

print('Welcome to Ibn Tharwat Scraper.')
print('This script scraps data from Ibn Sina System.')

#Creating security handshake (the expire) to use in every request to mimic human interaction
def make_expire():
    now = datetime.now()
    dt = ''
    if 0 >= now.hour >12 :
        dt = 'AM'
    else :
        dt = 'PM'
    return f'{now.day}/{now.month}/{now.year} {now.hour}:{now.minute}:{now.second}{dt}w{randint(1000,9999)}'

#Loggin in to Ibn sina patient management system
def login():
    session = requests.session()
    session.headers.update({'User-Agent':'Mozilla/5.0 Chrome/122.0.0.0','Referer':'https://srv137.mans.edu.eg/mus/IbnSena/login.py' ,'Origin':'https://srv137.mans.edu.eg',})
    cred = {'Username':'27812081602049',
            'Password':'123456',
            'comeFrom':'index',}
    url = f'https://srv137.mans.edu.eg/mus/newSystem/loginAuth.py/login?sysID=13.&AppLang=A&expire={make_expire()}&browser=Chrome,146'
    session.get('https://srv137.mans.edu.eg/mus/IbnSena/login.py',timeout=20)
    response = session.post(url,cred,allow_redirects=True)
    if '/application.py/frames?expire' in response.text :
        print('Logged in Succesfully.')
    else :
        print('Error logging in...')
    return(session)

#Fetch all patients in orthopedic department
def get_ortho_patients(session):
    patients = []
    url = f'https://srv137.mans.edu.eg/mus/IbnSena/Examination/examination.py?appID=13.20.1.&exp={make_expire()}&doIndex=getPatient&status=current&admissionSelect=&roomNo=---&filter=InDept&InstID=******&instID=******&ScopeID=1.34.102.&foundType='   
    r= session.get(url,timeout=20)
    r.encoding = 'utf-8'
    pattern = r'id="n(\d+)".*?title="(.*?)"'
    matches = re.findall(pattern, r.text)
    for idn, cname in matches :
        patients.append([idn,cname,'1.34.102.'])
    return patients

#Fetch all patients in general surgery department
def get_general_patients(session):
    patients = []
    url = f'https://srv137.mans.edu.eg/mus/IbnSena/Examination/examination.py?appID=13.20.1.&exp={make_expire()}&doIndex=getPatient&status=current&admissionSelect=&roomNo=---&filter=InDept&InstID=******&instID=******&ScopeID=1.34.104.&foundType='   
    r= session.get(url,timeout=20)
    r.encoding = 'utf-8'
    pattern = r'id="n(\d+)".*?title="(.*?)"'
    matches = re.findall(pattern, r.text)
    for idn, cname in matches :
        patients.append([idn,cname,'1.34.104.'])
    return patients

#Fetch all patients in ICU
def get_icu_patients(session):
    patients = []
    url = f'https://srv137.mans.edu.eg/mus/IbnSena/Examination/examination.py?appID=13.20.1.&exp={make_expire()}&doIndex=getPatient&status=current&admissionSelect=&roomNo=---&filter=InDept&InstID=******&instID=******&ScopeID=1.34.109.&foundType='   
    r= session.get(url,timeout=20)
    r.encoding = 'utf-8'
    pattern = r'id="n(\d+)".*?title="(.*?)"'
    matches = re.findall(pattern, r.text)
    for idn, cname in matches :
        patients.append([idn,cname,'1.34.109.'])
    return patients

#Fetch all patients
def get_current_list(session):
    ortho_patients = get_ortho_patients(session)
    general_patients = get_general_patients(session)
    icu_patients = get_icu_patients(session)
    all_patients = ortho_patients + general_patients + icu_patients
    return all_patients

#Update Google Spreadsheet
def update_sheet(data):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open('OrthoResident').sheet1
    sheet.update(data,'A2')

    
s = login()
patients_list = get_current_list(s)
def fetch_all_lap(session,patients):
    col = ['SGPT(ALT)','Serum Total Bilirubin','SGOT(AST)','Serum Albumin',
           'Creatinine','Fasting blood glucose','Anti - HCV','Anti - HIV',
           'HBs Ag','Blood Group','RH factor','WBC','HGB','PLT','INR']
    for idn,cname,scope in patients[:3] :
        url = f'https://srv137.mans.edu.eg/mus/IbnSena/Labs/displayAllInvestigations.py?appID=13.20.1.&exp={make_expire()}&InstID={idn}'
        r = s.get(url)
        r.encoding = 'utf-8'
        pattern = r'<b>(.*?)\s*</span>\s*<td.*?>\s*<span.*?>\s*([^<]+)'
        matches = re.findall(pattern,r.text)
        seen = set()
        for match in reversed(matches) :
            if match[0] in col and match[0] not in seen:
                print(match)
                #print(r.text)
                seen.add(match[0])
print(f'Total of {len(patients_list)} patients found.')
fetch_all_lap(s,patients_list)
print('End of Script.')
