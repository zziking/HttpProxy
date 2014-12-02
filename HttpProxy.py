#_*_ encoding:utf-8 _*_
#
#HTTP代理
#

import http.server
import http.cookiejar
import urllib.request
import urllib.response
import gzip
import threading
import socketserver
import ThreadPool


http.client.HTTPConnection.debuglevel = 0

class KIZRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    def __init__(self, request, client_address, server, request_interceptors=[]):
        self.request_interceptors = request_interceptors
        super().__init__(request, client_address, server)
    
    def do_GET(self):
        valid = self.checkRequest()
        if valid:
            self.processRequest(method='GET')

 
    def do_POST(self):
        valid = self.checkRequest()
        if valid:    
            self.processRequest(method='POST')
    
    def checkRequest(self):
        #接收到请求时，按顺序调用拦截器链
        for interceptor in self.request_interceptors:
            interceptor.beforeRequest(self)
        
        if 'Host' in self.headers.keys():
            self.host = self.headers['Host']
            parseResult = urllib.parse.urlparse(self.path)
            if parseResult.netloc is not None:
                self.uri = self.path
            else:
                self.uri = 'http://' + self.host + self.path
            #self.parseParam()
            return True
        else:
            print('Host is not assigned!')
            self.send_response(400) #Bad Request
            self.end_headers()
            self.wfile.write(b'Host not assigned!')
            return False
    
    #解析请求参数
    def parseParam(self):
        encode = 'UTF-8'
        self.queryParams = []
        if 'Content-Length' in self.headers.keys():   #POST请求体里的参数
            datas = self.rfile.read(int(self.headers['Content-Length'])).decode(encode, 'ignore')
            datas = urllib.parse.unquote(datas, encoding=encode)
            self.queryParams = urllib.parse.parse_qsl(datas, encoding=encode)
        if '?' in self.path:
            query = urllib.parse.splitquery(self.path)
            if query[1]:#接收get参数
                #由于不知道URL中的编码是GBK还是UTF-8,所以先使用UTF-8编码来解码，如果解码的结果再编码后和原来不一致，则不是UTF-8编码
                queryPms = urllib.parse.unquote(query[1], encoding=encode)
                tmp = urllib.parse.quote(queryPms, encoding=encode, safe='=&')
                if tmp != query[1]:
                    encode = 'GBK'
                params = urllib.parse.parse_qsl(query[1], encoding=encode)
                for p in params:
                    self.queryParams.append(p)      
    
    def processRequest(self, method=None):
        request = None
        if method.upper() == 'GET':
            request = urllib.request.Request(self.uri, headers=self.headers, method='GET')

        elif method.upper() == 'POST':
            datas = self.rfile.read(int(self.headers['Content-Length']))
            request = urllib.request.Request(self.uri, data=datas, headers=self.headers, method='POST')            

        else:
            self.send_response(501)
            self.end_headers()
            msg = '<h1><b>Unsupported Method:{0}</b></h1>'.format(method)
            self.wfile.write(msg.encode())
            return
        
        try:
            resp = urllib.request.urlopen(request, timeout=1.5)#超时时间(分钟)
        except urllib.error.HTTPError as e:
            self.send_response(504)
            self.end_headers()
            self.wfile.write(b'<h1><b>Gateway Timeout</b></h1>')
            print(e.code, e.reason)
            return
        
        self.respCode   = resp.getcode()
        self.respHeader = resp.info()
        self.respData   = resp.read()
        
        #如果响应的HTTP报头中指定了是gzip压缩，则先解压缩
        if self.respHeader['Content-Encoding'] == 'gzip' or self.respData.startswith(b'\x1f\x8b'):
            self.respData = gzip.decompress(self.respData)
            #返回给客户端是gzip解压后的数据，所以删除gzip压缩报头
            del self.respHeader['Content-Encoding']
            
        #收到转发后的HTTP请求响应时，调用拦截器链
        for interceptor in self.request_interceptors:
            interceptor.afterRequest(self)
        
        #如果修改了返回给客户端的内容，或者解压缩了gzip，必须修改Content-Length报头
        if self.respHeader['Content-Length']:
            self.respHeader.replace_header('Content-Length', str(len(self.respData)))
        
        self.send_response(self.respCode)
        self.send_headers(self.respHeader)
        self.end_headers()
        self.wfile.write(self.respData)
        
        
    #设置响应HTTP头
    def send_headers(self, headers={}):
        for key in headers.keys():
            self.send_header(key, headers[key])

 
class KIZRequestInterceptor:
    
    def __init__(self):
        pass
    
    def beforeRequest(self, kizRequestHandler):
        #print(kizRequestHandler.requestline)
        pass
    
    def afterRequest(self, kizRequestHandler):
        contenType = kizRequestHandler.respHeader['Content-Type']
        if  'text/html' in contenType.lower():
            kizRequestHandler.respData += b'<script>alert("inject code")</script>'
        pass
    
      
class KIZHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    '''
    代理不自动重定向，所有的重定向响应直接返回给客户端
    '''
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return fp
    
    #Moved Permanently
    def http_error_301(self, req, fp, code, msg, httpmsg):
        #self.updateHeader(req, fp)
        return fp
    
    #Move Temporarily
    def http_error_302(self, req, fp, code, msg, httpmsg):
        #self.updateHeader(req, fp)
        #return super().http_error_302(req, fp, code, msg, httpmsg)
        return fp
    
    #See Other
    def http_error_303(self, req, fp, code, msg, headers):
        #self.updateHeader(req, fp)
        return fp
    
    #Temporary Redirect
    def http_error_307(self, req, fp, code, msg, headers):
        #self.updateHeader(req, fp)
        return fp
    
    def updateHeader(self, req, fp):
        """
        本代理会自动重定向HTTP请求时，需要修改HTTP报头中的Host
        修改Request的Header中的Host属性为重定向指向的域名
        由于urllib处理发送重定向后的请求时，会把原来的request的HTTP Header原封不动的带上，所以要修改Header中的Host
        """
        location = fp.getheader('Location')
        parseResult = urllib.parse.urlparse(location)
        req.headers.update({'Host':parseResult.netloc})


class KIZHttpErrorHandler(urllib.request.HTTPDefaultErrorHandler):
    '''
    服务端返回的HTTP错误处理：所有的错误均不做处理，直接返回给客户端
    '''
    def http_error_default(self, req, fp, code, msg, hdrs):
        return fp
        '''
        if code == 304: #Not Modified
            return fp
        else:
            print(fp.geturl)
            print(fp.getheaders())
            return super().http_error_default(req, fp, code, msg, hdrs)
        '''

class KIZThreadingHTTPServer(http.server.HTTPServer): 
    #----------------------------------------------------------------------
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True, thread_num = 10, RequestInterceptorClasses=[]):
            """Constructor.  
            thread_num 线程池默认的线程数量
            
            """
            self.requestInterceptorClasses = RequestInterceptorClasses
            #初始化线程池
            self.threadPool = ThreadPool.ThreadPool(thread_num)
            #设置urllib opener， HTTP server接收到请求时，需要通过urllib 转发出请求，这里全局设置urllib
            cj = http.cookiejar.CookieJar() 
            #proxyHandler = urllib.request.ProxyHandler({'http','127.0.0.1:8888'}) 代理
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), KIZHTTPRedirectHandler, KIZHttpErrorHandler)
            urllib.request.install_opener(opener)    
            
            super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        
    #----------------------------------------------------------------------
    def process_request(self, request, client_address):
        """
        构造一个任务，提交给线程池执行
        """
        work = ThreadPool.WorkRequest(super().process_request, args = (request, client_address))
        self.threadPool.putRequest(work)
        
    #调用RequestHandler处理HTTP请求
    def finish_request(self, request, client_address):
        if self.RequestHandlerClass == KIZRequestHandler:
            interceptors = []
            for interceptorClass in self.requestInterceptorClasses:
                interceptors.append(interceptorClass())
            self.RequestHandlerClass(request, client_address, self, interceptors)
        else:
            self.RequestHandlerClass(request, client_address, self)

server_address = ('127.0.0.1', 8080)
httpd = KIZThreadingHTTPServer(server_address, KIZRequestHandler, thread_num=20, RequestInterceptorClasses=[KIZRequestInterceptor])  
print("Server started on %s, port %d....."%(server_address[0], server_address[1]))  
httpd.serve_forever()  