"""
These are just the constants we use everywhere.  

Tests may import this file to verify expected errors / help is parrotted back
"""

# we should autogen this from __doc__ strings
help_msg = """
This message is here because Johan hasn't hooked up a swagger endpoint yet.
In the mean-time. 

GET 

/help -> this message.
/env  -> return a simple json dict of current state. e.g
         { 'temperature': { 'unit': 'centigrade', 'value': 23.5}} # environmental temp

/history -> history of commands
"""

 

