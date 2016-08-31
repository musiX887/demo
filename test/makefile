TARGET := TEST 
objs := $(wildcard *.c) $(wildcard *.cpp)

$(TARGET): $(objs)
	    g++ -o $(TARGET)  $(objs) -g -std=c++0x -L/usr/lib/x86_64-linux-gnu  -L/usr/local/lib -lboost_regex -luuid

$objs: $(wildcard *.h)

format:
	    astyle --ascii --style=allman --indent-namespaces --pad-oper --align-pointer=name --align-reference=name --add-brackets --break-blocks --pad-paren-in --unpad-paren --fill-empty-lines $(wildcard *.hpp) $(wil    dcard *.h) $(wildcard 

clean: #清楚目标文件和中间文件。
	    rm $(TARGET) 
