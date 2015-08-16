#coding=utf8

from __future__ import division
import time
import traceback
import math

import gevent
from gevent.pool import Pool
from gevent.queue import Queue, JoinableQueue
from gevent import monkey 
monkey.patch_all()

import utils.gevent_pycurl as pycurl



class GreenletWorker(object):
    """ greenlet worker

    Attributes:
        url: url
        result_queue: 结果队列
    """

    def __init__(self, url):
        self.url = url
#        self.result_queue = result_queue
        self.c = pycurl.Curl()
        # 指定HTTP重定向的最大数
        self.c.setopt(pycurl.MAXCONNECTS, 1)    
        # 强制获取新的连接，即替代缓存中的连接
        self.c.setopt(pycurl.FRESH_CONNECT, 1)
        self.c.setopt(self.c.WRITEFUNCTION, self.set_body_size)
        self.c.setopt(self.c.HEADERFUNCTION, self.set_head_size)
        self.head_size = 0
        self.body_size = 0

    def __call__(self, stats):
        url = self.url
        result = self.get_url(url)
        stats.add(result)

    def set_head_size(self, buf):
        self.head_size += len(buf)

    def set_body_size(self, buf):
        self.body_size += len(buf)

    def clear_var(self):
        """恢复size变量
        """
        self.body_size = 0
        self.head_size = 0

    def get_url(self, url):
        """get result from url

        args:
            url: string url
        """
        total_start = time.time()

        self.c.setopt(pycurl.URL, url)
        try:
            self.c.perform()
        except:
            traceback.print_exc()
            return None
        else:
            status = self.c.getinfo(pycurl.RESPONSE_CODE)
            html_size = self.body_size
            total_size = self.body_size + self.head_size

            self.clear_var()
            total_time = time.time() - total_start
            time_dict = {}
            time_dict["total_time"] = self.c.getinfo(pycurl.TOTAL_TIME)
            time_dict["connect_time"] = self.c.getinfo(pycurl.CONNECT_TIME)
            time_dict["wait_time"] = self.c.getinfo(pycurl.STARTTRANSFER_TIME)
            time_dict["proc_time"] = time_dict["total_time"] - time_dict["connect_time"]
            return Result(time_dict, total_size, html_size, status)

class Result(object):
    """请求返回需要数据类

    Attributes:
           time_dict: time dict
               connect_time: the amount of time it took for the socket to open
               proc_time: first byte + transfer
               wait_time: time till first byte
               total_time: Sum of Connect + Processing
           total_size: The total number of bytes received from the server
           html_size: The total number of document bytes received from the server 
           status: http response status code
    """
    def __init__(self, time_dict, total_size, 
            html_size, status):
        self.total_time = time_dict["total_time"]
        self.connect_time = time_dict["connect_time"]
        self.proc_time = time_dict["proc_time"]
        self.waiting_time = time_dict["wait_time"]
        self.total_size = total_size
        self.html_size = html_size
        self.status = status
    
    def __str__(self):
        return 'Result(%s, %d, %d)' % (self.time_dict, self.total_size, self.status)

class ResultStats(object):
    """结果统计汇总统计类

    Attributes:
        results: 请求结果Result列表
    """
    def __init__(self):
        self.results = []
    
    def add(self, result):
        self.results.append(result)
    
    @property
    def failed_requests(self):
        return sum(1 for r in self.results if r.status != 200)
    
    @property
    def total_req_time(self):
        return sum(r.total_time for r in self.results)

    @property
    def avg_req_time(self):
        return self.total_req_time / len(self.results)
    
    @property
    def total_req_length(self):
        return sum(r.total_size for r in self.results)
    
    @property
    def html_req_length(self):
        return sum(r.html_size for r in self.results)

    @property
    def avg_req_length(self):
        return self.total_req_length / len(self.results)
    
    def distribution(self):
        """请求分布

           return: list
        """
        results = sorted(r.total_time for r in self.results)
        dist = []
        n = len(results)
        for p in (50, 66, 75, 80, 90, 95, 98, 99):
            i = p/100 * n
            i = n-1 if i >= n else int(i)
            dist.append((p, results[i]))
        dist.append((100, results[-1]))
        return dist

    def connection_times(self):
        """连接时间计算""" 

        connect = [r.connect_time for r in self.results]
        process = [r.proc_time for r in self.results]
        wait = [r.waiting_time for r in self.results]
        total = [r.total_time for r in self.results]
        
        square_sum = lambda l: sum(x*x for x in l)
        # 平均数
        mean = lambda l: sum(l)/len(l)
        # 方差
        deviations = lambda l, mean: [x-mean for x in l]
        # 标准方差
        def std_deviation(l):
            n = len(l)
            if n == 1:
                return 0
            return math.sqrt(square_sum(deviations(l, mean(l)))/(n-1))
        # 中位数
        median = lambda l: sorted(l)[int(len(l)//2)]
            
        results = []
        for data in (connect, process, wait, total):
            results.append((min(data), mean(data), std_deviation(data),
                            median(data), max(data)))
        return results


class TaskPool(object):

    def __init__(self, url, c, n):
        self.url = url
        pool = Pool(c)
        pool.start()

    def add_handler(self, stats):
        if self.pool.full(): 
            raise Exception("At maximum pool size")
        else:
            self.pool.spawn(GreenletWorker(self.url), stats)



class ApacheBench(object):
    """apache bench 控制类
    
    Attributes:
        c: concurrency, Number of multiple requests to perform at a time 
        n: number  of requests to perform for the benchmarking session
        t: timelimit, Maximum  number of seconds to spend for benchmarking. This implies a -n 50000 internally.
           Use this to benchmark the server within a fixed total amount of time. Per default there is no timelimit.
        url: url
    """

    def __init__(self, url, c=1, n=1, t=50000):
        self.c = c
        self.n = n
        self.url = url

    def start(self):
        
        print 'Benchmarking (be patient).....'

        result_queue = JoinableQueue()
        pool = Pool(self.c)
        stats = ResultStats()
        start = time.time()
        for _ in xrange(self.n):
            pool.spawn(GreenletWorker(self.url), stats)
        pool.join()


#        stats.add(result_queue.get())

        stop = time.time()
        total = stop - start
        print 'done'
        print ''
        print ''
        print 'Average Document Length: %.0f bytes' % (stats.avg_req_length,)
        print ''
        print 'Concurrency Level:    %d' % (self.c,)
        print 'Time taken for tests: %.3f seconds' % (total,)
        print 'Complete requests:    %d' % (len(stats.results),)
        print 'Failed requests:      %d' % (stats.failed_requests,)
        print 'Total transferred:    %d bytes' % (stats.total_req_length,)
        print 'HTML transferred:    %d bytes' % (stats.html_req_length,)
        print 'Requests per second:  %.2f [#/sec] (mean)' % (len(stats.results)/total,)
        print 'Time per request:     %.3f [ms] (mean)' % (stats.avg_req_time*1000,)
        print 'Time per request:     %.3f [ms] (mean, across all concurrent requests)' % (
                                                stats.avg_req_time*1000/self.c,)
        print 'Transfer rate:        %.2f [Kbytes/sec] received' % (stats.total_req_length/total/1024,)
        print ''
        print 'Connection Times (ms)'
        print '              min  mean[+/-sd] median   max'
        names = ('Connect', 'Processing', 'Waiting', 'Total')
        for name, data in zip(names, stats.connection_times()):
            t_min, t_mean, t_sd, t_median, t_max = [v*1000 for v in data] # to [ms]
            t_min, t_mean, t_median, t_max = [round(v) for v in (t_min, t_mean,
                                              t_median, t_max)]
            print '%-11s %5d %5d %5.1f %6d %7d' % (name+':', t_min, t_mean, t_sd,
                                                           t_median, t_max)
        print ''
        print 'Percentage of the requests served within a certain time (ms)'
        for percent, seconds in stats.distribution():
            print ' %3d%% %6.0f' % (percent, seconds*1024),
            if percent == 100:
                print '(longest request)'
            else:
                print ""

def main():
    from optparse import OptionParser
    usage = "usage: %prog [options] url(s)"
    parser = OptionParser(usage=usage)
    parser.add_option('-c', None, dest='c', type='int', default=1,
                      help='number of concurrent requests')
    parser.add_option('-n', None, dest='n', type='int', default=1,
                      help='total number of requests')
    parser.add_option('-t', None, dest='t', type='int', default=50000,
                      help='timelimit, Maximum number\
                      of seconds to spend for benchmarking')
    (options, args) = parser.parse_args()
    if len(args) == 1:
        import urlparse
	judge_url=urlparse.urlparse(args[0])
	if judge_url.scheme=="http" or judge_url.scheme=="https":
	  urls = args[0]
	else:
   	  parser.error("need the right URL(s)")
    else:
        parser.error('need one  URL(s)')
    bench = ApacheBench(urls, c=options.c, n=options.n, t=options.t)
    bench.start()

if __name__ == '__main__':
    main()
