import datetime
import logging
import urllib
import urllib2
import uuid
from xml.dom import minidom

# Smartly import hashlib and fall back on md5
try: from hashlib import md5
except ImportError: from md5 import md5


def make_utf8(dictionary):
    '''
    Encodes all Unicode strings in the dictionary to UTF-8. Converts
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


class ScormCloudError(Exception):
    def __init__(self, msg, json=None):
        self.msg = msg
        self.json = json
    def __str__(self):
        return repr(self.msg)


class ScormCloudService(object):
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


class CourseData(object):
    course_id = ""
    number_of_versions = 1
    number_of_registrations = 0
    title = ""

    def __init__(self, course_data_element):
        if course_data_element is not None:
            self.course_id = course_data_element.attributes['id'].value
            self.number_of_versions = course_data_element.attributes['versions'].value
            self.number_of_registrations = course_data_element.attributes['registrations'].value
            self.title = course_data_element.attributes['title'].value

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def convert_to_course_data_list(data):
        xmldoc = minidom.parseString(data)
        all_results = []
        courses = xmldoc.getElementsByTagName("course")
        for course in courses:
            all_results.append(CourseData(course))
        return all_results


class CourseService(ScormCloudService):
    def import_uploaded_course(self, courseid, path):
        if courseid is None:
            courseid = str(uuid.uuid1())
        data = self.scormcloud_call(method='rustici.course.importCourse',
            path=path, courseid=courseid)
        return ImportResult.convert_to_import_results(data)

    def delete_course(self, courseid, delete_latest_version_only=False):
        params = {}
        params['courseid'] = courseid
        params['method'] = "rustici.course.deleteCourse"
        if delete_latest_version_only:
            params['versionid'] = 'latest'
        data = self.scormcloud_call(**params)

    def get_assets(self, courseid, path=None):
        if path is not None:
            data = self.scormcloud_call(method='rustici.course.getAssets',
                courseid=courseid, path=path)
        else:
            data = self.scormcloud_call(method='rustici.course.getAssets',
                courseid=courseid)
        return data

    def get_course_list(self, course_id_filter_regex=None):
        if course_id_filter_regex is not None:
            data = self.scormcloud_call(method='rustici.course.getCourseList',
                filter=course_id_filter_regex)
        else:
            data = self.scormcloud_call(method='rustici.course.getCourseList')
        courseList = CourseData.convert_to_course_data_list(data)
        return courseList

    def get_preview_url(self, courseid, redirecturl, stylesheet_url=None):
        params = {}
        params['method'] = "rustici.course.preview"
        params['courseid'] = courseid
        params['redirecturl'] = redirecturl
        if stylesheet_url is not None:
            params['stylesheet'] = stylesheet_url

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def get_course_metadata(self, courseid):
        return self.scormcloud_call(method='rustici.course.getMetadata',
            courseid=courseid)

    def get_property_editor_url(self, courseid, stylesheet_url=None,
        notificationFrameUrl=None):

        params = {}
        params['method'] = "rustici.course.properties"
        params['courseid'] = courseid
        if stylesheet_url is not None:
            params['stylesheet'] = stylesheet_url
        if notificationFrameUrl is not None:
            params['notificationframesrc'] = notificationFrameUrl

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def get_attributes(self, courseid, versionid=None):
        params = {}
        params['method'] = "rustici.course.getAttributes"
        params['courseid'] = courseid
        if versionid is not None:
            params['versionid'] = versionid
        data = self.scormcloud_call(**params)
        xmldoc = minidom.parseString(data)
        attr_nodes = xmldoc.getElementsByTagName('attribute')
        atts = {}
        for an in attr_nodes:
            atts[an.attributes['name'].value] = an.attributes['value'].value
        return atts

    def update_attributes(self, courseid, versionid, attribute_pairs):
        params = {}
        params['method'] = "rustici.course.updateAttributes"
        params['courseid'] = courseid
        if versionid is not None:
            params['versionid'] = versionid
        params.update(attribute_pairs)
        data = self.scormcloud_call(**params)
        xmldoc = minidom.parseString(data)
        attr_nodes = xmldoc.getElementsByTagName('attribute')
        atts = {}
        for an in attr_nodes:
            atts[an.attributes['name'].value] = an.attributes['value'].value
        return atts


class DebugService(ScormCloudService):
    def cloud_auth_ping(self):
        data = self.scormcloud_call(method='rustici.debug.authPing')
        xmldoc = minidom.parseString(data)
        return xmldoc.documentElement.attributes['stat'].value == 'ok'

    def cloud_ping(self):
        data = self.scormcloud_call(method='rustici.debug.ping')
        xmldoc = minidom.parseString(data)
        return xmldoc.documentElement.attributes['stat'].value == 'ok'


class ImportResult(object):
    was_successful = False
    title = ""
    message = ""
    parser_warnings = []

    def __init__(self, import_result_element):
        if import_result_element is not None:
            self.was_successful = \
                import_result_element.attributes['successful'].value == 'true'
            self.title = import_result_element.getElementsByTagName(
                "title")[0].childNodes[0].nodeValue
            self.message = import_result_element.getElementsByTagName(
                "message")[0].childNodes[0].nodeValue
            xmlpw = import_result_element.getElementsByTagName("warning")
            for pw in xmlpw:
                self.parser_warnings.append(pw.childNodes[0].nodeValue)

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def convert_to_import_results(data):
        xmldoc = minidom.parseString(data)
        all_results = []
        importresults = xmldoc.getElementsByTagName("importresult")
        for ir in importresults:
            all_results.append(ImportResult(ir))
        return all_results


class RegistrationData(object):
    courseId = ""
    registration_id = ""

    def __init__(self, reg_data_element):
        if reg_data_element is not None:
            self.courseId = reg_data_element.attributes['courseid'].value
            self.registration_id = reg_data_element.attributes['id'].value

    def  __getattr__(self, attrib):
        return self.attrib

    @staticmethod
    def convert_to_registration_data_list(data):
        xmldoc = minidom.parseString(data)
        all_results = []
        regs = xmldoc.getElementsByTagName("registration")
        for reg in regs:
            all_results.append(RegistrationData(reg))
        return all_results


class RegistrationService(ScormCloudService):
    def create_registration(self, regid, courseid, userid, fname, lname,
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
        success_nodes = xmldoc.getElementsByTagName('success')
        if success_nodes.length == 0:
            raise ScormCloudError("Create Registration failed.  " + \
                xmldoc.err.attributes['msg'] )
        return regid

    def get_launch_url(self, regid, redirecturl, course_tags=None,
        learner_tags=None, registration_tags=None):

        redirecturl = redirecturl + "?regid=" + regid
        params = {
            'method': 'rustici.registration.launch',
            'appid': self.appid,
            'regid': regid,
            'redirecturl': redirecturl,
        }
        if course_tags is not None:
            params['course_tags'] = course_tags
        if learner_tags is not None:
            params['learner_tags'] = learner_tags
        if registration_tags is not None:
            params['registration_tags'] = registration_tags

        sig = self.encode_and_sign(params)
        url = '%s?' % (self.servicehost + '/api')
        url = url + sig
        return url

    def get_registration_list(self, reg_id_filter_regex=None,
        course_id_filter_regex=None):

        params = {}
        params['method'] = "rustici.registration.getRegistrationList"
        if reg_id_filter_regex is not None:
            params['filter'] = reg_id_filter_regex
        if course_id_filter_regex is not None:
            params['coursefilter'] = course_id_filter_regex

        data = self.scormcloud_call(**params)
        return RegistrationData.convert_to_registration_data_list(data)

    def get_registration_result(self, regid, resultsformat,
        dataformat=None):

        params = {}
        params['method'] = "rustici.registration.getRegistrationResult"
        params['regid'] = regid
        params['resultsformat'] = resultsformat
        if dataformat is not None:
            params['format'] = dataformat
        return self.scormcloud_call(**params)

    def get_launch_history(self, regid):
        return self.scormcloud_call(
            method='rustici.registration.getLaunchHistory', regid=regid)

    def reset_registration(self, regid):
        return self.scormcloud_call(
            method='rustici.registration.resetRegistration', regid=regid)

    def reset_global_objectives(self, regid, delete_latest_instance_only=True):
        params = {}
        params['method'] = "rustici.registration.resetGlobalObjectives"
        params['regid'] = regid
        if delete_latest_instance_only:
            params['instanceid'] = 'latest'
        return self.scormcloud_call(**params)

    def delete_registration(self, regid, delete_latest_instance_only=False):
        params = {}
        params['method'] = "rustici.registration.deleteRegistration"
        params['regid'] = regid
        if delete_latest_instance_only:
            params['instanceid'] = 'latest'
        return self.scormcloud_call(**params)


class UploadService(ScormCloudService):
    def get_upload_token(self):
        data = self.scormcloud_call(method='rustici.upload.getUploadToken')
        xmldoc = minidom.parseString(data)
        server_nodes = xmldoc.getElementsByTagName('server')
        tokenid_nodes = xmldoc.getElementsByTagName('id')
        server = None
        for s in server_nodes:
            server = s.childNodes[0].nodeValue
        tokenid = None
        for t in tokenid_nodes:
            tokenid = t.childNodes[0].nodeValue
        if server and tokenid:
            token = UploadToken(server, tokenid)
            return token
        else:
            return None

    def get_upload_url(self, importurl):
        token = self.get_upload_token()
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

    def delete_file(self, location):
        loc_parts = location.split("/")
        params = {}
        params['file'] = loc_parts[1]
        params['method'] = "rustici.upload.deleteFiles"
        return self.scormcloud_call(**params)


class UploadToken(object):
    server = ""
    tokenid = ""
    def __init__(self, server, tokenid):
        self.server = server
        self.tokenid = tokenid

    def __getattr__(self, attrib):
        return self.attrib
