#!/usr/bin/python

from __future__ import division
import sys
import os
import Queue
import threading
import time
import traceback
import itertools
from urllib2 import build_opener, urlopen, HTTPError

import signal

keep_processing = True

def stop_processing(_signal, _frame):
    global keep_processing
    print 'STOP'
    keep_processing = False
    return 0

signal.signal(signal.SIGINT, stop_processing)

class URLGetter(threading.Thread):
    def __init__(self, url_queue, result_queue):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.url_queue = url_queue
        self.result_queue = result_queue
        self.opener = build_opener()
    def run(self):
        while keep_processing:
            url = self.url_queue.get()
            if url is None:
                break
            result = self.get_url(url)
            self.url_queue.task_done()
            self.result_queue.put(result)
    def get_url(self, url):
        start = time.time()
        size = status = 0
        try:
            result = self.opener.open(url)
            size = len(result.read())
            status = result.code
        except HTTPError, e:
            size = len(e.read())
            status = e.code
        except:
            traceback.print_exc()
        total_time = time.time() - start
        return Result(total_time, size, status)

class URLGetterPool(object):
    def __init__(self, size=2):
        self.size = size
        self.url_queue = Queue.Queue(100)
        self.result_queue = Queue.Queue()
        self.getter = []
    def start(self):
        for _ in xrange(self.size):
            t = URLGetter(self.url_queue, self.result_queue)
            t.start()
            self.getter.append(t)

class URLProducer(threading.Thread):
    def __init__(self, url_queue, urls, n=10):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.url_queue = url_queue
        self.n = n
        self.url = urls
    
    def run(self):
        for _ in xrange(self.n):
          self.url_queue.put(self.url)
    

class Result(object):
    def __init__(self, time, size, status):
        self.time = time
        self.size = size
        self.status = status
    
    def __repr__(self):
        return 'Result(%.5f, %d, %d)' % (self.time, self.size, self.status)

class ResultStats(object):
    def __init__(self):
        self.results = []
    
    def add(self, result):
        self.results.append(result)
    
    @property
    def failed_requests(self):
        return sum(1 for r in self.results if r.status != 200)
    
    @property
    def total_req_time(self):
        return sum(r.time for r in self.results)

    @property
    def avg_req_time(self):
        return self.total_req_time / len(self.results)
    
    @property
    def total_req_length(self):
        return sum(r.size for r in self.results)
    
    @property
    def avg_req_length(self):
        return self.total_req_length / len(self.results)
    
    def distribution(self):
	results = sorted(r.time for r in self.results)
        dist = []
        n = len(results)
        for p in (50, 66, 75, 80, 90, 95, 98, 99):
            i = p/100 * n
            i = n-1 if i >= n else int(i)
            dist.append((p, results[i]))
        dist.append((100, results[-1]))
        return dist

class WebBench(object):
    def __init__(self, urls, c=1, n=1):
        self.c = c
        self.n = n
        self.urls = urls
    def start(self):
        out = sys.stdout
        
        pool = URLGetterPool(self.c)
        pool.start()

        producer = URLProducer(pool.url_queue, self.urls, n=self.n)
        
        print 'Benchmarking (be patient).....',
        
        start = time.time()
        producer.start()

        stats = ResultStats()

        for _ in xrange(self.n):
            if not keep_processing:
                break
            stats.add(pool.result_queue.get())

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
        print 'Requests per second:  %.2f [#/sec] (mean)' % (len(stats.results)/total,)
        print 'Time per request:     %.3f [ms] (mean)' % (stats.avg_req_time*1000,)
        print 'Time per request:     %.3f [ms] (mean, across all concurrent requests)' % (
                                                stats.avg_req_time*1000/self.c,)
        print 'Transfer rate:        %.2f [Kbytes/sec] received' % (stats.total_req_length/total/1024,)
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
    bench = WebBench(urls, c=options.c, n=options.n)
    bench.start()

if __name__ == '__main__':
    main()
