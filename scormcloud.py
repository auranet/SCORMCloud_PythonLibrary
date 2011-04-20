import sys
import urllib
import urllib2
import mimetools
import os.path
import logging
import copy
import webbrowser
import datetime

import cgi
# Smartly import hashlib and fall back on md5
try: from hashlib import md5
except ImportError: from md5 import md5

from xml.dom import minidom
import uuid

def make_utf8(dictionary):
    '''Encodes all Unicode strings in the dictionary to UTF-8. Converts
    all other objects to regular strings.

    Returns a copy of the dictionary, doesn't touch the original.
    '''

    result = {}
    for (key, value) in dictionary.iteritems():
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        else:
            value = str(value)
        result[key] = value
    return result

class ScormCloudApi(object):
    def __init__(self, appid, secret, servicehost):
        self.appid = appid
        self.secret = secret
        self.servicehost = servicehost
        self.__handler_cache = {}

    def  __getattr__(self, attrib):
        return self.attrib

    def sign(self, dictionary):
        data = [self.secret]
        for key in sorted(dictionary.keys()):
            data.append(key)
            datum = dictionary[key]
            if isinstance(datum, unicode):
                raise IllegalArgumentException(
                    "No Unicode allowed, "
                    "argument %s (%r) should "
                    "have been UTF-8 by now" % (key, datum))
            data.append(datum)
        md5_hash = md5(''.join(data))
        return md5_hash.hexdigest()

    def encode_and_sign(self, dictionary):
        '''
        URL encodes the data in the dictionary, and signs it using the
        given secret, if a secret was given.
        '''
        dictionary['appid'] = self.appid
        dictionary['ts'] = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        dictionary = make_utf8(dictionary)
        if self.secret:
            dictionary['sig'] = self.sign(dictionary)
        return urllib.urlencode(dictionary)


    def scormcloud_call(self, **kwargs):
        post_data = self.encode_and_sign(kwargs)
        url = self.servicehost + '/api'
        response = urllib2.urlopen(url, post_data)
        reply = response.read()
        response.close()
        return reply


class DebugService(ScormCloudApi):
    def CloudAuthPing(self):
        data = self.scormcloud_call(method='rustici.debug.authPing')
        xmldoc = minidom.parseString(data)
        #logging.info('cloudauthping: ' + str(xmldoc.documentElement.attributes['stat'].value))
        return xmldoc.documentElement.attributes['stat'].value == 'ok'

    def CloudPing(self):
        data = self.scormcloud_call(method='rustici.debug.ping')
        xmldoc = minidom.parseString(data)
        return xmldoc.documentElement.attributes['stat'].value == 'ok'


class UploadService(ScormCloudApi):
    def GetUploadToken(self):
        data = self.scormcloud_call(method='rustici.upload.getUploadToken')
        xmldoc = minidom.parseString(data)
        serverNodes = xmldoc.getElementsByTagName('server')
        tokenidNodes = xmldoc.getElementsByTagName('id')
        server = None
        for s in serverNodes:
            server = s.childNodes[0].nodeValue
        tokenid = None
        for t in tokenidNodes:
            tokenid = t.childNodes[0].nodeValue
        if server and tokenid:
            token = UploadToken(server, tokenid)
            return token
        else:
            return None

    def GetUploadUrl(self, importurl):
        token = self.GetUploadToken()
        if token:
            params = {
                'method': 'rustici.upload.uploadFile',
                'appid': self.appid,
                'tokenid': token.tokenid,
                'redirecturl': importurl,
            }
            sig = self.encode_and_sign(params)
            url =  '%s/api?' % (self.servicehost)
            url = url + sig
            return url
        else:
            return None

    def DeleteFile(self, location):
        locParts = location.split("/")
        params = {}
        params['file'] = locParts[1]
        params['method'] = "rustici.upload.deleteFiles"
        return self.scormcloud_call(**params)


class CourseService(ScormCloudApi):
    def ImportUploadedCourse(self, courseid, path):
        if courseid is None:
            courseid = str(uuid.uuid1())
        data = self.scormcloud_call(method='rustici.course.importCourse',
            path=path, courseid=courseid)
        ir = ImportResult.ConvertToImportResults(data)
        return ir

    def DeleteCourse(self, courseid, deleteLatestVersionOnly=False):
        params = {}
        params['courseid'] = courseid
        params['method'] = "rustici.course.deleteCourse"
        if deleteLatestVersionOnly:
            params['versionid'] = 'latest'
        data = self.scormcloud_call(**params)

    def GetAssets(self, courseid, path=None):
        if path is not None:
            data = self.scormcloud_call(method='rustici.course.getAssets',
                courseid=courseid, path=path)
        else:
            data = self.scormcloud_call(method='rustici.course.getAssets',
                courseid=courseid)
        return data

    def GetCourseList(self, courseIdFilterRegex=None):
        if courseIdFilterRegex is not None:
            data = self.scormcloud_call(method='rustici.course.getCourseList',
                filter=courseIdFilterRegex)
        else:
            data = self.scormcloud_call(method='rustici.course.getCourseList')
        courseList = CourseData.ConvertToCourseDataList(data)
        return courseList

    def GetPreviewUrl(self, courseid, redirecturl, stylesheetUrl=None):
        params = {}
        params['method'] = "rustici.course.preview"
        params['courseid'] = courseid
        params['redirecturl'] = redirecturl
        if stylesheetUrl is not None:
            params['stylesheet'] = stylesheetUrl

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def GetCourseMetadata(self, courseid):
        return self.scormcloud_call(method='rustici.course.getMetadata',
            courseid=courseid)

    def GetPropertyEditorUrl(self, courseid, stylesheetUrl=None,
        notificationFrameUrl=None):

        params = {}
        params['method'] = "rustici.course.properties"
        params['courseid'] = courseid
        if stylesheetUrl is not None:
            params['stylesheet'] = stylesheetUrl
        if notificationFrameUrl is not None:
            params['notificationframesrc'] = notificationFrameUrl

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def GetAttributes(self, courseid, versionid=None):
        params = {}
        params['method'] = "rustici.course.getAttributes"
        params['courseid'] = courseid
        if versionid is not None:
            params['versionid'] = versionid
        data = self.scormcloud_call(**params)
        xmldoc = minidom.parseString(data)
        attrNodes = xmldoc.getElementsByTagName('attribute')
        atts = {}
        for an in attrNodes:
            atts[an.attributes['name'].value] = an.attributes['value'].value
        return atts

    def UpdateAttributes(self, courseid, versionid, attributePairs):
        params = {}
        params['method'] = "rustici.course.updateAttributes"
        params['courseid'] = courseid
        if versionid is not None:
            params['versionid'] = versionid
        params.update(attributePairs)
        data = self.scormcloud_call(**params)
        xmldoc = minidom.parseString(data)
        attrNodes = xmldoc.getElementsByTagName('attribute')
        atts = {}
        for an in attrNodes:
            atts[an.attributes['name'].value] = an.attributes['value'].value
        return atts

class RegistrationService(ScormCloudApi):
    def CreateRegistration(self, regid, courseid, userid, fname, lname,
        email=None):

        if regid is None:
            regid = str(uuid.uuid1())
        params = {}
        params['method'] = "rustici.registration.createRegistration"
        params['appid'] = self.appid
        params['courseid'] = courseid
        params['regid'] = regid
        params['fname'] = fname
        params['lname'] = lname
        params['learnerid'] = userid
        if email is not None:
            params['email'] = email
        data = self.scormcloud_call(**params)
        xmldoc = minidom.parseString(data)
        successNodes = xmldoc.getElementsByTagName('success')
        if successNodes.length == 0:
            raise ScormCloudError("Create Registration failed.  " + xmldoc.err.attributes['msg'] )
        return regid

    def GetLaunchUrl(self, regid, redirecturl, courseTags=None,
        learnerTags=None, registrationTags=None):

        redirecturl = redirecturl + "?regid=" + regid
        params = {
            'method': 'rustici.registration.launch',
            'appid': self.appid,
            'regid': regid,
            'redirecturl': redirecturl,
        }
        if courseTags is not None:
            params['courseTags'] = courseTags
        if learnerTags is not None:
            params['learnerTags'] = learnerTags
        if registrationTags is not None:
            params['registrationTags'] = registrationTags

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def GetRegistrationList(self, regIdFilterRegex=None,
        courseIdFilterRegex=None):

        params = {}
        params['method'] = "rustici.registration.getRegistrationList"
        if regIdFilterRegex is not None:
            params['filter'] = regIdFilterRegex
        if courseIdFilterRegex is not None:
            params['coursefilter'] = courseIdFilterRegex

        data = self.scormcloud_call(**params)
        regList = RegistrationData.ConvertToRegistrationDataList(data)
        return regList

    def GetRegistrationResult(self, regid, resultsformat,
        dataformat=None):

        params = {}
        params['method'] = "rustici.registration.getRegistrationResult"
        params['regid'] = regid
        params['resultsformat'] = resultsformat
        if dataformat is not None:
            params['format'] = dataformat
        data = self.scormcloud_call(**params)
        return data

    def GetLaunchHistory(self, regid):
        return self.scormcloud_call(
            method='rustici.registration.getLaunchHistory', regid=regid)

    def ResetRegistration(self, regid):
        return self.scormcloud_call(
            method='rustici.registration.resetRegistration', regid=regid)

    def ResetGlobalObjectives(self, regid, deleteLatestInstanceOnly=True):
        params = {}
        params['method'] = "rustici.registration.resetGlobalObjectives"
        params['regid'] = regid
        if deleteLatestInstanceOnly:
            params['instanceid'] = 'latest'
        data = self.scormcloud_call(**params)
        return data

    def DeleteRegistration(self, regid, deleteLatestInstanceOnly=False):
        params = {}
        params['method'] = "rustici.registration.deleteRegistration"
        params['regid'] = regid
        if deleteLatestInstanceOnly:
            params['instanceid'] = 'latest'

        data = self.scormcloud_call(**params)
        return data

class ScormCloudError(Exception):
    def __init__(self, msg, json=None):
        self.msg = msg
        self.json = json
    def __str__(self):
        return repr(self.msg)

class ImportResult(object):
    wasSuccessful = False
    title = ""
    message = ""
    parserWarnings = []

    def __init__(self,importResultElement):
        if importResultElement is not None:
            self.wasSuccessful = importResultElement.attributes['successful'].value == 'true'
            self.title = importResultElement.getElementsByTagName("title")[0].childNodes[0].nodeValue
            self.message = importResultElement.getElementsByTagName("message")[0].childNodes[0].nodeValue
            xmlpw = importResultElement.getElementsByTagName("warning")
            for pw in xmlpw:
                self.parserWarnings.append(pw.childNodes[0].nodeValue)

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def ConvertToImportResults(data):
        xmldoc = minidom.parseString(data)
        allResults = [];
        importresults = xmldoc.getElementsByTagName("importresult")
        for ir in importresults:
            allResults.append(ImportResult(ir))
        return allResults

class CourseData(object):
    courseId = ""
    numberOfVersions = 1
    numberOfRegistrations = 0
    title = ""

    def __init__(self,courseDataElement):
        if courseDataElement is not None:
            self.courseId = courseDataElement.attributes['id'].value
            self.numberOfVersions = courseDataElement.attributes['versions'].value
            self.numberOfRegistrations = courseDataElement.attributes['registrations'].value
            self.title = courseDataElement.attributes['title'].value;

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def ConvertToCourseDataList(data):
        xmldoc = minidom.parseString(data)
        allResults = [];
        courses = xmldoc.getElementsByTagName("course")
        for course in courses:
            allResults.append(CourseData(course))
        return allResults

class UploadToken(object):
    server = ""
    tokenid = ""
    def __init__(self,server,tokenid):
        self.server = server
        self.tokenid = tokenid

    def __getattr__(self, attrib):
        return self.attrib

class RegistrationData(object):
    courseId = ""
    registrationId = ""

    def __init__(self,regDataElement):
        if regDataElement is not None:
            self.courseId = regDataElement.attributes['courseid'].value
            self.registrationId = regDataElement.attributes['id'].value

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def ConvertToRegistrationDataList(data):
        xmldoc = minidom.parseString(data)
        allResults = [];
        regs = xmldoc.getElementsByTagName("registration")
        for reg in regs:
            allResults.append(RegistrationData(reg))
        return allResults
