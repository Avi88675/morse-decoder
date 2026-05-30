"""
International Morse Code table.
ITU standard — covers letters, numbers, and common punctuation.
"""

MORSE_TO_CHAR = {
    # Letters
    '.-':   'A', '-...': 'B', '-.-.': 'C', '-..':  'D',
    '.':    'E', '..-.': 'F', '--.':  'G', '....': 'H',
    '..':   'I', '.---': 'J', '-.-':  'K', '.-..': 'L',
    '--':   'M', '-.':   'N', '---':  'O', '.--.': 'P',
    '--.-': 'Q', '.-.':  'R', '...':  'S', '-':    'T',
    '..-':  'U', '...-': 'V', '.--':  'W', '-..-': 'X',
    '-.--': 'Y', '--..': 'Z',

    # Numbers
    '-----': '0', '.----': '1', '..---': '2',
    '...--': '3', '....-': '4', '.....': '5',
    '-....': '6', '--...': '7', '---..': '8', '----.': '9',

    # Punctuation
    '.-.-.-': '.', '--..--': ',', '..--..': '?',
    '.----.': "'", '-.-.--': '!', '-..-.':  '/',
    '-.--.':  '(', '-.--.-': ')', '.-...':  '&',
    '---...': ':', '-.-.-.': ';', '-...-':  '=',
    '.-.-.':  '+', '-....-': '-', '..--.-': '_',
    '.-..-.': '"', '...-..-':'$', '.--.-.': '@',

    # European / accented characters (ITU standard)
    '.-.-':   'Ä', '---.':   'Ö', '..--.':  'Ü',
    '.--.-':  'À', '-.-..':  'Ç', '..-..':  'É',
    '.--..':  'Þ', '..--':   'Ð',

    # Prosigns (procedural signals used in CW operation)
    '.-...':  'AS',    # Wait
    '-...-':  'BK',    # Break
    '...-.': 'SK',    # End of contact
    '-.--.-': 'KN',   # Over (specific station only)
    '-.-':    'K',     # Invite to transmit (also a letter)
    '...---...': 'SOS',
}

# Reverse lookup for transmit
CHAR_TO_MORSE = {
    char: code
    for code, char in MORSE_TO_CHAR.items()
    if len(char) == 1  # only single characters
}
CHAR_TO_MORSE[' '] = ' '   # word space
