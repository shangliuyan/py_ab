
## Introduction
pyab is implemented by python which have same method with apache benchmark.
pyab is relyed on pycurl lib. 

## install
pip install -r requirement.txt

## usage
两个并发，10个请求，超时时间10s

```sh
python pyab.py -c 2 -n 10 -t 10 http://www.baidu.com/ 
```
