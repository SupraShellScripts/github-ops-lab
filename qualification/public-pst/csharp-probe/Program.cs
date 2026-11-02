// SPDX-License-Identifier: MIT
// Public-only fixture census for a pinned third-party PSTFileFormat read/write library.
// No subjects, addresses, bodies, filenames, or attachment bytes are printed.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using PSTFileFormat;

if (args.Length != 1) { Console.Error.WriteLine("one file argument required"); return 2; }
var output = new Dictionary<string, object?>();
try
{
    using var guard = new FileStream(args[0], FileMode.Open, FileAccess.Read, FileShare.Read);
    if (guard.Length > 2_000_000) throw new InvalidDataException("size cap");
    guard.Dispose();
    PSTFile pst = new PSTFile(args[0], FileAccess.Read);
    try
    {
        int folders = 0, messages = 0, attachments = 0, unsupportedFolders = 0, notesRead = 0;
        var stack = new Stack<(PSTFolder folder, int depth)>();
        stack.Push((pst.TopOfPersonalFolders, 0));
        while (stack.Count > 0)
        {
            var (folder, depth) = stack.Pop();
            if (depth > 40 || ++folders > 5000) throw new InvalidDataException("folder traversal limit");
            messages += folder.MessageCount;
            if (messages > 5000) throw new InvalidDataException("message count limit");
            if (folder is MailFolder mail)
            {
                for (int i = 0; i < mail.MessageCount; i++)
                {
                    var note = mail.GetNote(i);
                    attachments += note.AttachmentCount;
                    notesRead++;
                    if (attachments > 5000) throw new InvalidDataException("attachment count limit");
                }
            }
            else if (folder.MessageCount > 0)
            {
                unsupportedFolders++;
            }
            foreach (var child in folder.GetChildFolders()) stack.Push((child, depth + 1));
        }
        output["status"] = unsupportedFolders == 0 ? "ENUMERATED_MAIL_SCOPED" : "PARTIAL_NONMAIL_CLASSES";
        output["folderCount"] = folders;
        output["folderReportedItemCount"] = messages;
        output["notesRead"] = notesRead;
        output["attachmentCount"] = attachments;
        output["unsupportedNonMailFolders"] = unsupportedFolders;
        output["nativeMAPICompleteness"] = "UNVERIFIED";
    }
    finally { pst.CloseFile(); }
}
catch (Exception ex)
{
    // Public runner stdout may be retained. Exception type only, never message or stack trace.
    output["status"] = "FAILED";
    output["errorType"] = ex.GetType().Name;
    output["nativeMAPICompleteness"] = "UNVERIFIED";
}
Console.WriteLine(JsonSerializer.Serialize(output));
return 0;
