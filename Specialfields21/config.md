* All fields are special: (false or true, without quote) whether every field keeps its local value when a note is updated by an import
* Combine tagging: (false or true) true keeps every local tag alongside the imported ones. False keeps only imported tags plus local tags containing a protected phrase, "marked" or "leech"
* Protected tags: phrases (case sensitive) that keep a local tag when Combine tagging is false
* Special field: list of field names that keep their local value when a note is updated by an import. Each field name between quotes, separated by commas
* update deck description: true always takes the imported deck description, false always keeps yours (new decks always take the imported one)
* update note styling: true always updates note types from the package, false never does, null keeps the choice made on Anki's import screen
* update only if newer: true updates a note only when the package copy is newer, false updates every matching note (choosing "Never" on Anki's import screen still wins). Notes the add-on restores get the time of your import as their modification time, so with true a later package whose edits are older than that import is skipped

Settings apply when you answer yes to "Import using the Special Fields add-on?" after choosing a deck package.
