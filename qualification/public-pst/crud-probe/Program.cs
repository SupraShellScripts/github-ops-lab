// Public synthetic PST CRUD probe, linked against pinned ContinuMail PSTFileFormat.
// NEVER run against originals: caller supplies an already-created disposable copy.
// No source message text or addresses emitted.
using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using PSTFileFormat;
if (args.Length != 1) { Console.Error.WriteLine("one disposable PST path required"); return 2; }
var path = args[0];
PSTFile? file = null;
try
{
    if (!File.Exists(path) || new FileInfo(path).Length > 2_000_000)
        throw new InvalidDataException("source must be bounded, preexisting stage");
    file = new PSTFile(path, FileAccess.ReadWrite, WriterCompatibilityMode.Outlook2007RTM);
    file.BeginSavingChanges();
    var top = file.TopOfPersonalFolders;
    var src = top.GetChildFolders().FirstOrDefault(f => f.DisplayName == "sample") as MailFolder
        ?? throw new InvalidDataException("expected synthetic sample mail folder");
    if (src.MessageCount != 2) throw new InvalidDataException("expected two source notes");
    Note update = src.GetNote(0);
    Note delete = src.GetNote(1);
    if (update == null || delete == null) throw new InvalidDataException("missing note");
    // UPDATE a native message; do not change its source occurrence in the original.
    update.Subject = "PST-CRUD-UPDATED";
    update.Body = "PST-CRUD-UPDATED-BODY";
    update.SaveChanges();
    src.UpdateMessage(update);
    // DELETE a distinct existing item logically from the staged output.
    src.DeleteMessage(delete);
    src.SaveChanges();
    // CREATE a new folder and a new message in the staged output.
    var addedFolder = top.CreateChildFolder("PST-CRUD-ADDED-FOLDER", FolderItemTypeName.Note);
    var added = Note.CreateNewNote(file, addedFolder.NodeID);
    added.Subject = "PST-CRUD-ADDED";
    added.Body = "PST-CRUD-ADDED-BODY";
    added.SaveChanges();
    addedFolder.AddMessage(added);
    addedFolder.SaveChanges();
    top.SaveChanges();
    file.EndSavingChanges();
    file.CloseFile();
    file = null;
    // Independently reopen through the same native reader for basic persisted topology.
    var verify = new PSTFile(path, FileAccess.Read);
    try
    {
        var folders = verify.TopOfPersonalFolders.GetChildFolders();
        var sample = folders.FirstOrDefault(f => f.DisplayName == "sample") as MailFolder;
        var created = folders.FirstOrDefault(f => f.DisplayName == "PST-CRUD-ADDED-FOLDER") as MailFolder;
        if (sample == null || created == null) throw new InvalidDataException("missing expected folders");
        if (sample.MessageCount != 1 || created.MessageCount != 1)
            throw new InvalidDataException("unexpected persisted mail counts");
        if (sample.GetNote(0).Subject != "PST-CRUD-UPDATED" ||
            sample.GetNote(0).Body != "PST-CRUD-UPDATED-BODY" ||
            created.GetNote(0).Subject != "PST-CRUD-ADDED" ||
            created.GetNote(0).Body != "PST-CRUD-ADDED-BODY")
            throw new InvalidDataException("subject/body update or create not persisted");
        Console.WriteLine(JsonSerializer.Serialize(new {
            schema = "public-native-pst-copy-on-write-crud/v1",
            nativeReadback = "PASS",
            updatedOriginalCount = sample.MessageCount,
            newlyCreatedCount = created.MessageCount,
            targetTotalNotes = sample.MessageCount + created.MessageCount,
            createdFolderPresent = true,
            sourceOriginalImmutable = "VALIDATE_IN_WRAPPER",
            nativeMAPICompleteness = "UNVERIFIED"
        }));
    }
    finally { verify.CloseFile(); }
    return 0;
}
catch(Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(new {
        schema = "public-native-pst-copy-on-write-crud/v1",
        status="FAILED",
        errorType=ex.GetType().Name,
        nativeMAPICompleteness="UNVERIFIED"
    }));
    return 1;
}
finally { if (file != null) file.CloseFile(); }
