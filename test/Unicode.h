#ifndef __UNICODE_H_67842__
#define __UNICODE_H_67842__
#include <wchar.h>
#include <stdlib.h>

#define str_ansi char
#define str_ucs2 wchar_t
#define str_utf8 char

str_ansi * GetANSIFromUTF8(const str_utf8 * pUTF8);

str_ansi * GetANSIFromUCS2(const str_ucs2 * pUCS2);

str_ucs2 * GetUCS2FromANSI(const str_ansi * pANSI);

str_ucs2 * GetUCS2FromUTF8(const str_utf8 * pUTF8);

str_utf8 * GetUTF8FromANSI(const str_ansi * pANSI);

str_utf8 * GetUTF8FromUCS2(const str_ucs2 * pUCS2);





//����str�ַ���Ŀ
int get_utf8_length(const char *str);


//get�Ӵ� ������һ�����ַ�������Ҫ������ȥ�ͷ�
char* sub_utf8_string(const char *str, unsigned int start, unsigned int end);
#endif
