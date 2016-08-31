//#include "depends.h"
#include "Unicode.h"
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <locale.h>

str_ansi * GetANSIFromUTF8(const str_utf8 * pUTF8)
{
	str_ucs2 * pUCS2 = GetUCS2FromUTF8(pUTF8);
	str_ansi * pANSI = GetANSIFromUCS2(pUCS2);
	free(pUCS2);
	return pANSI;
}

str_ansi * GetANSIFromUCS2(const str_ucs2 * pUCS2)
{
	const int nCharacters = pUCS2 ? (int)wcslen(pUCS2) : 0;
	int nANSICharacters = (2 * nCharacters);
	str_ansi * pANSI = (str_ansi*)malloc(sizeof(str_ansi)*(nANSICharacters+1));
	memset(pANSI, 0, (nANSICharacters + 1) * sizeof(str_ansi));
	if (pUCS2)
#ifdef _WIN32
		WideCharToMultiByte(CP_ACP, 0, pUCS2, -1, pANSI, nANSICharacters, NULL, NULL);
#else
	{
		setlocale(LC_CTYPE, "");
		wcstombs(pANSI, pUCS2, nANSICharacters);
	}
#endif

	return (str_ansi *) pANSI;
}

str_ucs2 * GetUCS2FromANSI(const str_ansi * pANSI)
{
	const int nCharacters = pANSI ? (int)strlen(pANSI) : 0;
	str_ucs2 * pUCS2 = (str_ucs2*)malloc(sizeof(str_ucs2)*(nCharacters+1));
	memset(pUCS2, 0, sizeof(str_ucs2) * (nCharacters + 1));
	if (pANSI)
#ifdef _WIN32
		MultiByteToWideChar(CP_ACP, 0, pANSI, -1, pUCS2, nCharacters);
#else
	{
		setlocale(LC_CTYPE, "");
		mbstowcs(pUCS2, pANSI, nCharacters);
	}
#endif

	return pUCS2;
}

str_ucs2 * GetUCS2FromUTF8(const str_utf8 * pUTF8)
{
	// get the length
	int nCharacters = 0; int nIndex = 0;
	while (pUTF8[nIndex] != 0)
	{
		if ((pUTF8[nIndex] & 0x80) == 0)
			nIndex += 1;
		else if ((pUTF8[nIndex] & 0xE0) == 0xE0)
			nIndex += 3;
		else
			nIndex += 2;

		nCharacters += 1;
	}

	// make a UCS2 string
	str_ucs2 * pUCS2 = (str_ucs2*)malloc(sizeof(str_ucs2)*(nCharacters+1));
	nIndex = 0; nCharacters = 0;
	while (pUTF8[nIndex] != 0)
	{
		if ((pUTF8[nIndex] & 0x80) == 0)
		{
			pUCS2[nCharacters] = pUTF8[nIndex];
			nIndex += 1;
		}
		else if ((pUTF8[nIndex] & 0xE0) == 0xE0)
		{
			pUCS2[nCharacters] = ((pUTF8[nIndex] & 0x1F) << 12) | ((pUTF8[nIndex + 1] & 0x3F) << 6) | (pUTF8[nIndex + 2] & 0x3F);
			nIndex += 3;
		}
		else
		{
			pUCS2[nCharacters] = ((pUTF8[nIndex] & 0x3F) << 6) | (pUTF8[nIndex + 1] & 0x3F);
			nIndex += 2;
		}

		nCharacters += 1;
	}
	pUCS2[nCharacters] = 0;

	return pUCS2;
}

str_utf8 * GetUTF8FromANSI(const str_ansi * pANSI)
{
	str_ucs2 * pUCS2 = GetUCS2FromANSI(pANSI);
	str_utf8 * pUTF8 = GetUTF8FromUCS2(pUCS2);
	free(pUCS2);
	return pUTF8;
}

str_utf8 * GetUTF8FromUCS2(const str_ucs2 * pUCS2)
{
	// get the size(s)
	int nCharacters = (int)wcslen(pUCS2);
	int nUTF8Bytes = 0;
	for (int z = 0; z < nCharacters; z++)
	{
		if (pUCS2[z] < 0x0080)
			nUTF8Bytes += 1;
		else if (pUCS2[z] < 0x0800)
			nUTF8Bytes += 2;
		else
			nUTF8Bytes += 3;
	}

	// allocate a UTF-8 string
	str_utf8 * pUTF8 = (str_utf8*)malloc(sizeof(str_utf8)*(nUTF8Bytes+1));

	// create the UTF-8 string
	int nUTF8Index = 0;
	for (int z = 0; z < nCharacters; z++)
	{
		if (pUCS2[z] < 0x0080)
		{
			pUTF8[nUTF8Index++] = (str_utf8) pUCS2[z];
		}
		else if (pUCS2[z] < 0x0800)
		{
			pUTF8[nUTF8Index++] = 0xC0 | (pUCS2[z] >> 6);
			pUTF8[nUTF8Index++] = 0x80 | (pUCS2[z] & 0x3F);
		}
		else
		{
			pUTF8[nUTF8Index++] = 0xE0 | (pUCS2[z] >> 12);
			pUTF8[nUTF8Index++] = 0x80 | ((pUCS2[z] >> 6) & 0x3F);
			pUTF8[nUTF8Index++] = 0x80 | (pUCS2[z] & 0x3F);
		}
	}
	pUTF8[nUTF8Index++] = 0;

	// return the UTF-8 string
	return pUTF8;
}


//utf8字符长度1-6，可以根据每个字符第一个字节判断整个字符长度
//0xxxxxxx
//110xxxxx 10xxxxxx
//1110xxxx 10xxxxxx 10xxxxxx
//11110xxx 10xxxxxx 10xxxxxx 10xxxxxx
//111110xx 10xxxxxx 10xxxxxx 10xxxxxx 10xxxxxx
//1111110x 10xxxxxx 10xxxxxx 10xxxxxx 10xxxxxx 10xxxxxx
//
//定义查找表，长度256，表中的数值表示以此为起始字节的utf8字符长度
unsigned char utf8_look_for_table[] ={
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
	2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
	2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
	3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
	4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 1, 1
};

#define UTFLEN(x)  utf8_look_for_table[(x)]

int get_utf8_length(const char *str) {
    int byte_len = strlen(str);
    int len = 0;

    for (char *ptr = (char*)str;
            *ptr != 0 && len < byte_len;
            len++, ptr += UTFLEN((unsigned char) *ptr));

    return len;
}


char* sub_utf8_string(const char *str, unsigned int start, unsigned int end)
{
    int len = get_utf8_length(str);

    if (start >= len) return NULL;
    if (end > len) end = len;

    char *start_ptr = (char*)str;
    for (int i = 0; i < start; ++i, start_ptr += UTFLEN((unsigned char) *start_ptr))
        ;

    char *end_ptr = start_ptr;
    for (int i = start; i < end; ++i, end_ptr += UTFLEN((unsigned char) *end_ptr))
        ;

    int ret_len = end_ptr - start_ptr;
    char *ret_str = (char*) malloc(ret_len + 1);
    memcpy(ret_str, start_ptr, ret_len);
    ret_str[ret_len] = 0;

    return ret_str;
}
