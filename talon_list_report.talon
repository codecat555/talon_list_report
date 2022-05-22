

# search for talon lists matching the pattern formed by joining the given words with underscores,
# e.g. 'show talon list report file manager directories' for the list 'user.file_manager_directories'.
show talon list report (<phrase>):
    user.show_talon_list_report(user.formatted_text(phrase, "SNAKE_CASE"))
