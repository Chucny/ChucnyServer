

# this just has one variable to determite if hacker mode is gonna be on or not





HACKER_MODE = False

def flip_hackermode():
    global HACKER_MODE
    HACKER_MODE = not HACKER_MODE
    return HACKER_MODE

def get_hackermode():
    return HACKER_MODE