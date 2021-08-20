# -*- coding: utf-8 -*-

from xml.etree.ElementTree import fromstring, tostring
import xml.etree.ElementTree as ET
import json

ns = {
    "wps": "http://www.opengis.net/wps/2.0",
    "ows": "http://www.opengis.net/ows/2.0"
}


def set_namespaces(xml_element):
    xml_element.set("xmlns:wps", "http://www.opengis.net/wps/2.0")
    xml_element.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    xml_element.set("xmlns:schemaLocation", "http://schemas.opengis.net/wps/2.0/wps.xsd")
    xml_element.set("xmlns:ows", "http://www.opengis.net/ows/2.0")

    return xml_element


def get_status(job_status):
    """
    Translate HySDS job status to WPS status
    :param job_status:
    :return:
    """
    if job_status == "job-queued":
        status = "Accepted"
    elif job_status == "job-started":
        status = "Running"
    elif job_status == "job-completed":
        status = "Succeeded"
    elif job_status == "job-failed":
        status = "Failed"
    elif job_status == "job-revoked":
        status = "Dismissed"
    elif job_status == "Deleted" or job_status is None:
        status = "Deleted"
    else:
        """
        if job is deduped or offline setting it to failed
        because technically the job didn't complete
        """
        status = "Failed"

    return status


def parse_execute_request(request_xml):
    """
    OGC EXECUTE REQUEST

    <wps:Execute xmlns:wps="http://www.opengis.net/wps/2.0"
 xmlns:ows="http://www.opengis.net/ows/2.0" xmlns:xlink="http://www.w3.org/1999/xlink"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.opengis.net/wps/2.0 ../wps.xsd" service="WPS"
       version="2.0.0" response="document" mode="sync">
       <ows:Identifier>algo_id:version</ows:Identifier>
             <wps:Input id="data">
                      <wps:Reference schema="http://schemas.opengis.net/gml/3.1.1/base/feature.xsd" xlink:href="http://geoprocessing.demo.52north.org:8080/geoserver/wfs?SERVICE=WFS&amp;VERSION=1.0.0&amp;REQUEST=GetFeature&amp;TYPENAME=topp:tasmania_roads&amp;SRS=EPSG:4326&amp;OUTPUTFORMAT=GML3"/>
             </wps:Input>
 <wps:Input id="width">
    <wps:Data><wps:LiteralValue>0.05</wps:LiteralValue></wps:Data>
 </wps:Input>
      <wps:Output id="result" transmission="value"/>
</wps:Execute>

    :return:
    """
    root = fromstring(request_xml)
    params = dict()
    dedup = None
    queue = None
    job_type = root.find('ows:Identifier', ns).text
    for input in root.findall('wps:Input', ns):
        for data in input.findall('wps:Data', ns):
            for value in data.findall('wps:LiteralValue', ns):
                if input.attrib.get("id") == "dedup":
                    dedup = value.text
                if input.attrib.get("id") == "queue":
                    queue = value.text
                else:
                    try:
                        params[input.attrib.get("id")] = json.loads(value.text)
                    except ValueError:
                        params[input.attrib.get("id")] = value.text

    output = root.find('wps:Output', ns).attrib.get("id")

    return job_type, params, queue, output, dedup


def execute_response(job_id, job_status, output):
    """
    OGC EXECUTE RESPONSE

    <wps:Result xmlns:wps="http://www.opengis.net/wps/2.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.opengis.net/wps/2.0 http://schemas.opengis.net/wps/2.0/wps.xsd">
    <wps:JobID>3a097ae3-d3c0-4ba4-8b85-e6a4af3fe636</wps:JobID>
    <wps:Status>Accepted</wps:Status>
      <wps:Output id="result">
        <wps:Data schema="http://schemas.opengis.net/kml/2.2.0/ogckml22.xsd" mimeType="application/vnd.google-earth.kml+xml">
      </wps:Output>
    </wps:Result>

    :param job_id:
    :param job_status:
    :param output:
    :return:
    """
    status = get_status(job_status)
    response = ET.Element("wps:Result")
    response = set_namespaces(response)
    ET.SubElement(response, "wps:JobID").text = job_id
    ET.SubElement(response, "wps:Status").text = status
    ET.SubElement(response, "wps:{}".format(output.capitalize()))
    return tostring(response)


def parse_status_request(request_xml):
    """
    OCG GetStatus REQUEST EXAMPLE

    <wps:GetStatus service="WPS" version="2.0.0" xmlns:wps="http://www.opengis.net/wps/2.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/wps/2.0 ../wps.xsd ">
    <wps:JobID>336d5fa5-3bd6-4ee9-81ea-c6bccd2d443e</wps:JobID>
    </wps:GetStatus>

    :param request_xml:
    :return:
    """
    root = fromstring(request_xml)
    job_id = root.find('wps:JobID', ns).text
    return job_id


def parse_result_request(request_xml):
    """
    OCG GetResult REQUEST EXAMPLE

    <wps:GetResult service="WPS" version="2.0.0"
      xmlns:wps="http://www.opengis.net/wps/2.0"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:schemaLocation="http://www.opengis.net/wps/2.0 ../wps.xsd ">
      <wps:JobID>336d5fa5-3bd6-4ee9-81ea-c6bccd2d443e</wps:JobID>
    </wps:GetResult>​​​​​​​​​​​​​

    :param request_xml:
    :return:
    """
    root = fromstring(request_xml)
    job_id = root.find('wps:JobID', ns).text
    return job_id


def construct_product(xml_element, product):
    product_ele = ET.SubElement(xml_element, "wps:Product")
    ET.SubElement(product_ele, "wps:ProductName").text = product.get("id")
    locations = ET.SubElement(product_ele, "wps:Locations")
    for url in product.get("urls"):
        ET.SubElement(locations, "wps:Location").text = url
    return xml_element


def result_response(job_id, job_result=None, error=None):
    """
    OCG GetResult Response
    <wps:Result xsi:schemaLocation="http://www.opengis.net/wps/2.0 http://schemas.opengis.net/wps/2.0/wps.xsd" xmlns:wps="http://www.opengis.net/wps/2.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <wps:JobID>336d5fa5-3bd6-4ee9-81ea-c6bccd2d443e</wps:JobID>
    <wps:Output id="filename">
      <wps:Reference xlin:href="location of product on S3 bucket"/>
    </wps:Output>
    </wps:Result>​
    :param job_result:
    :return:
    """
    response = ET.Element("wps:Result")
    response = set_namespaces(response)
    ET.SubElement(response, "wps:JobID").text = job_id
    if job_result is not None:
        for product in job_result:
            output = ET.SubElement(response, "wps:Output")
            output.set("id", product.get("id"))
            for url in product.get("urls"):
                location = ET.SubElement(output, "wps:Data")
                location.text = url
            # products = construct_product(products, product)
    if error is not None:
        output = ET.SubElement(response, "wps:Output")
        output.set("id", "traceback")
        err = ET.SubElement(output, "wps:Data")
        err.text = error
    return tostring(response)


def status_response(job_id, job_status):
    """
    OGC GetStatus RESPONSE EXAMPLE

    <wps:StatusInfo xsi:schemaLocation="http://www.opengis.net/wps/2.0 http://schemas.opengis.net/wps/2.0/wps.xsd"
    xmlns:wps="http://www.opengis.net/wps/2.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <wps:JobID>336d5fa5-3bd6-4ee9-81ea-c6bccd2d443e</wps:JobID>
    <wps:Status>Succeeded</wps:Status>
    </wps:StatusInfo>

    :param job_id:
    :param job_status:
    :return:
    """

    status = get_status(job_status)
    response = ET.Element("wps:StatusInfo")
    response = set_namespaces(response)
    ET.SubElement(response, "wps:JobID").text = job_id
    ET.SubElement(response, "wps:Status").text = status

    return tostring(response)


def get_op(op_ele, op_name, get_url = None, post_url = None):
    op = ET.SubElement(op_ele, "ows:Operation")
    op.set("name", op_name)
    dcp = ET.SubElement(op, "ows:DCP")
    http = ET.SubElement(dcp, "ows:HTTP")
    if get_url is not None:
        get_ele = ET.SubElement(http, "ows:Get")
        get_ele.set("xlin:href", get_url)

    if post_url is not None:
        post_ele = ET.SubElement(http, "ows:Post")
        post_ele.set("xlin:href", post_url)

    return op_ele


def get_capabilities(base_url, job_list):
    """
    This creates a response containing service metadata such as the service name, keywords, and contact information for
    the organization operating the server.
    :param: takes in the list of algorigthms available in the DPS
    :return:
    """

    response = ET.Element("wps:Capabilities")
    response = set_namespaces(response)
    response.set("xmlns:ows", "http://www.opengis.net/ows/2.0")
    response.set("xmlns:xlin", "http://www.w3.org/1999/xlink")
    response.set("service", "WPS")
    response.set("version", "2.0.0")

    serv_id = ET.SubElement(response, "ows:ServiceIdentification")
    ET.SubElement(serv_id, "ows:Title").text = "Multi Mission Analysis Platform"
    ET.SubElement(serv_id, "ows:Abstract").text = "The MAAP Services are based on the OCG REST Specifications"
    keywords = ET.SubElement(serv_id, "ows:Keywords")
    ET.SubElement(keywords, "ows:Keyword").text = "MAAP"
    ET.SubElement(keywords, "ows:Keyword").text = "NASA"
    ET.SubElement(keywords, "ows:Keyword").text = "ESA"
    ET.SubElement(keywords, "ows:Keyword").text = "API"
    ET.SubElement(serv_id, "ows:ServiceType").text = "OCG"
    ET.SubElement(serv_id, "ows:ServiceTypeVersion").text = "0.0.1"
    ET.SubElement(serv_id, "ows:Fees").text = "NONE"
    ET.SubElement(serv_id, "ows:AccessConstraints").text = "NONE"

    serv_prov = ET.SubElement(response, "ows:ServiceProvider")
    ET.SubElement(serv_prov, "ows:ProviderName").text = "MAAP Team"
    provider_link = ET.SubElement(serv_prov, "ows:ProviderSite")
    provider_link.set("xlin:href", "https://www.jpl.nasa.gov/")
    serv_contact = ET.SubElement(serv_prov, "ows:ServiceContact")
    ET.SubElement(serv_contact, "ows:IndividualName").text = "Name"
    contact_info = ET.SubElement(serv_contact, "ows:ContactInfo")
    address = ET.SubElement(contact_info, "ows:Address")
    ET.SubElement(address, "ows:DeliveryPoint")
    ET.SubElement(address, "ows:City")
    ET.SubElement(address, "ows:AdministrativeArea")
    ET.SubElement(address, "ows:PostalCode")
    ET.SubElement(address, "ows:Country")
    ET.SubElement(address, "ows:ElectronicMailAddress")

    op_met = ET.SubElement(response, "ows:OperationsMetadata")
    op_met = get_op(op_met, "GetCapabilities", get_url=base_url + "api/dps/job?")
    op_met = get_op(op_met, "Execute", post_url=base_url + "api/dps/job")
    op_met = get_op(op_met, "GetStatus", get_url=base_url + "api/dps/job/<job_id>")
    op_met = get_op(op_met, "DescribeProcess", get_url=base_url + "api/mas/algorithm/<algorithm_id>")

    lang = ET.SubElement(response, "ows:Languages")
    ET.SubElement(lang, "ows.Language").text = "en-US"

    content = ET.SubElement(response, "wps:Contents")
    for job_type in job_list:
        proc_summ = ET.SubElement(content, "wps:ProcessSummary")
        proc_summ.set("processVersion", "1.0.0")
        proc_summ.set("jobControlOptions", "sync-execute async-execute")
        proc_summ.set("outputTransmission", "value reference")
        ET.SubElement(proc_summ, "ows:Title").text = "Algorithm: {} ; Version: {}"\
            .format(job_type.strip("job-").split(":")[0],
                    job_type.strip("job-").split(":")[1])
        ET.SubElement(proc_summ, "ows:Identifier").text = job_type.strip("job-")
        proc_metadata = ET.SubElement(proc_summ, "ows:Metadata")
        proc_metadata.set("xlin:role", "Process description")
        proc_metadata.set("xlin:href", base_url + "api/dps/job/describeprocess/{}%3A{}"
                          .format(job_type.strip("job-").split(":")[0],
                                  job_type.strip("job-").split(":")[1]))
    return tostring(response)


def parse_describe_process(request_xml):
    """
    <wps:DescribeProcess service="WPS" version="2.0.0"
    xmlns:ows="http://www.opengis.net/ows/2.0"
    xmlns:wps="http://www.opengis.net/wps/2.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/wps/2.0 http://schemas.opengis.net/wps/2.0/wps.xsd ">
    <ows:Identifier>job-type</ows:Identifier>
    </wps:DescribeProcess>
    :param request_xml:
    :return:
    """
    root = fromstring(request_xml)
    job_type = root.find('ows:Identifier', ns).text
    return job_type


def get_literal_data(input, value):
    literal_data = ET.SubElement(input, "ns:LiteralData")
    literal_data.set("xmlns:ns","http://www.opengis.net/wps/2.0")
    format_ele = ET.SubElement(literal_data, "ns:Format")
    format_ele.set("default","true")
    format_ele.set("mimeType","text/plain")
    domain = ET.SubElement(literal_data, "LiteralDataDomain")
    if value is None:
        ET.SubElement(domain, "ows:AnyValue")
        ET.SubElement(domain, "ows:DataType").set("ows:reference", "xs:string")
    else:
        data = ET.SubElement(domain, "wps:Data")
        ET.SubElement(data, "wps:LiteralValue").text = value

    return input


def get_input(process_xml, field, value=None):
    """
    <wps:Input minOccurs="1" maxOccurs="1">
        <ows:Title>width</ows:Title>
        <ows:Identifier>width</ows:Identifier>
        <ns:LiteralData xmlns:ns="http://www.opengis.net/wps/2.0">
          <ns:Format default="true" mimeType="text/plain"/>
          <ns:Format mimeType="text/xml"/>
          <LiteralDataDomain>
            <ows:AnyValue/>
            <ows:DataType ows:reference="xs:double"/>
          </LiteralDataDomain>
        </ns:LiteralData>
      </wps:Input>
    :param field:
    :return:
    """
    input = ET.SubElement(process_xml, "wps:Input")
    input.set("minOccurs","1")
    input.set("maxOccurs","1")
    ET.SubElement(input, "ows:Title").text = field
    ET.SubElement(input, "ows:Identifier").text = field
    get_literal_data(input, value)
    return process_xml


def describe_process_response(label, params, queue):
    """

    :param label:
    :param params:
    :return:
    """
    response = ET.Element("wps:ProcessOfferings")
    response = set_namespaces(response)
    offering = ET.SubElement(response, "wps:ProcessOffering")
    offering.set("processVersion", "1.1.0")
    offering.set("jobControlOptions", "sync-execute async-execute")
    offering.set("outputTransmission", "value reference")
    process = ET.SubElement(offering, "wps:Process")
    ET.SubElement(process, "ows:Title").text = "Algorithm: {} ; Version: {}"\
        .format(label.strip("job-").split(":")[0],
                label.strip("job-").split(":")[1])
    ET.SubElement(process, "ows:Identifier").text = label

    for param in params:
        process = get_input(process, param.get("name"))

    process = get_input(process, "queue_name", queue)

    ET.SubElement(process, "wps:Output")
    return tostring(response)


def get_exception(type, origin_process, ex_message):
    """
    <ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/ows/1.1 http://schemas.opengis.net/ows/1.1.0/owsExceptionReport.xsd" version="2.0.0">
    <ows:Exception exceptionCode="NoSuchProcess" locator="MyIncorrectProcessName">
    <ows:ExceptionText>One of the identifiers passed does not match with any of the processes offered by this server</ows:ExceptionText>
    </ows:Exception>
    </ows:ExceptionReport>
    :param type:
    :return:
    """
    response = ET.Element("ows:ExceptionReport")
    response = set_namespaces(response)
    exception = ET.SubElement(response, "ows:Exception")
    exception.set("exceptionCode", type)
    exception.set("locator", origin_process)
    ET.SubElement(exception, "ows:ExceptionText").text = ex_message

    return tostring(response)











