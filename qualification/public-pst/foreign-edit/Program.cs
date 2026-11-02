// Bounded third-party public PST native edit; ONLY run on disposable cloned input.
// This probes ability to update an existing PST not authored by our C# implementation.
// An unchanged source hash and independent readers are required in outer harness.
using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using PSTFileFormat;

if(args.Length != 1){Console.Error.WriteLine("require staged copy");return 2;}
PSTFile? pst = null;
try {
    var path = args[0];
    if(!File.Exists(path)||new FileInfo(path).Length>2_000_000)
        throw new InvalidDataException("stage size/preexistence guard");
    pst = new PSTFile(path,FileAccess.ReadWrite,WriterCompatibilityMode.Outlook2007RTM);
    pst.BeginSavingChanges();
    var mail = pst.TopOfPersonalFolders.GetChildFolders().OfType<MailFolder>()
             .Single(f=>f.MessageCount==1);
    var note = mail.GetNote(0);
    if(note.AttachmentCount!=1)throw new InvalidDataException("expected one original attachment");
    note.Subject = "FOREIGN-PST-UPDATED";
    // Outlook maintains a separate PidTagNormalizedSubject (0x0E1D).
    // The existing foreign store may have this, and readers can prefer it
    // over PidTagSubject. Probe a precise dual-property update on the stage.
    note.PC.SetStringProperty((PropertyID)0x0E1D, "FOREIGN-PST-UPDATED");
    note.Body = "FOREIGN-PST-UPDATED-BODY";
    note.SaveChanges();
    mail.UpdateMessage(note);
    mail.SaveChanges();
    pst.EndSavingChanges();
    pst.CloseFile();
    pst=null;
    var check = new PSTFile(path,FileAccess.Read);
    try{
        var after=check.TopOfPersonalFolders.GetChildFolders().OfType<MailFolder>()
            .Single(f=>f.MessageCount==1);
        var saved=after.GetNote(0);
        if(saved.Subject!="FOREIGN-PST-UPDATED"||
           saved.Body!="FOREIGN-PST-UPDATED-BODY"||
           saved.AttachmentCount!=1)
            throw new InvalidDataException("native persisted mutation failed");
        var pcSubject = saved.PC.GetStringProperty(PropertyID.PidTagSubject);
        var pcNormalized = saved.PC.GetStringProperty((PropertyID)0x0E1D);
        string? rowSubject = null;
        string? rowNormalized = null;
        try { rowSubject = after.GetMessageStringProperty(0, PropertyID.PidTagSubject); } catch {}
        try { rowNormalized = after.GetMessageStringProperty(0, (PropertyID)0x0E1D); } catch {}
        Console.WriteLine(JsonSerializer.Serialize(new{
            schema="public-foreign-pst-native-mutation/v2",
            status="MUTATED_REOPENED_CSHARP",
            pcSubjectHasExpectedToken = pcSubject?.Contains("FOREIGN-PST-UPDATED") ?? false,
            pcNormalizedSubjectHasExpectedToken = pcNormalized?.Contains("FOREIGN-PST-UPDATED") ?? false,
            rowSubjectHasExpectedToken = rowSubject?.Contains("FOREIGN-PST-UPDATED") ?? false,
            rowNormalizedSubjectHasExpectedToken = rowNormalized?.Contains("FOREIGN-PST-UPDATED") ?? false,
            messageCount=after.MessageCount,
            attachmentCount=saved.AttachmentCount,
            allMAPIPropertiesVerified=false
        }));
    }finally{check.CloseFile();}
    return 0;
}catch(Exception e){
    Console.WriteLine(JsonSerializer.Serialize(new{
        schema="public-foreign-pst-native-mutation/v1",status="BLOCKED",
        firstFailureType=e.GetType().Name,allMAPIPropertiesVerified=false
    }));
    return 3;
}finally{if(pst!=null)pst.CloseFile();}
