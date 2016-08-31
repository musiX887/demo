#include <stdio.h>
#include <iostream>
#include <stdlib.h>
#include <vector>
#include <algorithm>
#include <sstream>
#include <pthread.h>
#include <uuid/uuid.h>
#include <memory.h>
#include <ucontext.h>  
#include <unistd.h>  

using namespace std;

int main(int argc, const char *argv[]){  
    ucontext_t context;  
  
    getcontext(&context);  // tag1
    puts("Hello world");  
    sleep(1);  
    setcontext(&context);  // 这里回复上下文，会导致程序重新回tag1的位置。
    return 0;  
}  




