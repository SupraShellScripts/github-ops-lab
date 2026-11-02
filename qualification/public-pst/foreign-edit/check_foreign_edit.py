#!/usr/bin/env python3
"""Foreign-PST C# mutation public-only verifier. No raw mail content logged."""
from __future__ import annotations
from collections import Counter
from email import policy
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_public_pst import FIXTURES,get_bytes,verify_bytes

NAME="pstsdk-sample1.pst"
def run(args):
    try:
        result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              timeout=40,check=False)
        return result.returncode,result.stdout[:4096]
    except subprocess.TimeoutExpired:
        return None,b""

def eml_inventory(root):
    files=list(root.rglob("*.eml"))
    messages=[BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in files]
    blobs=Counter()
    for m in messages:
        for part in m.walk():
            if part.is_multipart(): continue
            if part.get_content_disposition()=="attachment":
                raw=part.get_payload(decode=True)
                if raw is not None: blobs[hashlib.sha256(raw).hexdigest()]+=1
    return files,messages,blobs

def main():
    if len(sys.argv)!=2:return 2
    dll=str(Path(sys.argv[1]).resolve())
    sha,size,version=FIXTURES[NAME]
    raw=get_bytes(NAME,size);verify_bytes(raw,sha,size,version)
    with tempfile.TemporaryDirectory(prefix="public-foreign-pst-edit-") as td:
        base=Path(td)
        source=base/"original.pst"
        stage=base/"staged.pst"
        source.write_bytes(raw)
        source.chmod(0o444)
        shutil.copyfile(source,stage)
        before=base/"before";before.mkdir()
        after=base/"after";after.mkdir()
        old_exit,_=run(["readpst","-q","-e","-o",str(before),str(source)])
        edit_exit,output=run(["dotnet",dll,str(stage)])
        row={"schema":"public-pst-foreign-native-mutation/v1","fixture":NAME,
             "source_sha256_verified":True,"source_reader_exit":old_exit,
             "edit_exit":edit_exit}
        try:
            safe=json.loads(output)
            row["native_result"]={k:v for k,v in safe.items() if k in
                                  ("status","firstFailureType","messageCount","attachmentCount")}
        except (ValueError,TypeError):row["native_result"]={"status":"UNPARSEABLE"}
        if edit_exit==0:
            row["pffinfo_exit"],_=run(["pffinfo",str(stage)])
            row["rewritten_readpst_exit"],_=run(["readpst","-q","-e","-o",str(after),str(stage)])
            orig_files,orig_messages,orig_blobs=eml_inventory(before)
            out_files,out_messages,out_blobs=eml_inventory(after)
            text=[]
            for msg in out_messages:
                for part in msg.walk():
                    if part.get_content_type()=="text/plain" and part.get_content_disposition()!="attachment":
                        b=part.get_payload(decode=True)
                        if b is not None:
                            text.append(b.decode(part.get_content_charset() or "utf-8",errors="replace"))
            expected="FOREIGN-PST-UPDATED"
            mutated_subjects=[str(m.get("Subject") or "").strip() for m in out_messages]
            source_subjects=[str(m.get("Subject") or "").strip() for m in orig_messages]
            row.update({
                "subject_changed_in_independent_export":source_subjects!=mutated_subjects,
                "expected_subject_token_contained":any(expected in subj for subj in mutated_subjects),
                "expected_subject_exact":any(subj==expected for subj in mutated_subjects),
                "original_eml_count":len(orig_files),
                "mutated_eml_count":len(out_files),
                "binary_sha_multiset_preserved":orig_blobs==out_blobs,
                "original_attachment_occurrences":sum(orig_blobs.values()),
                "mutated_attachment_occurrences":sum(out_blobs.values()),
                "edited_subject_seen":any(s==expected for s in mutated_subjects),
                "edited_body_seen":any("FOREIGN-PST-UPDATED-BODY" in s for s in text),
                "full_MAPI_bag_preserved":"UNVERIFIED"
            })
            passed=(
                row["pffinfo_exit"]==0 and row["rewritten_readpst_exit"]==0
                and len(orig_files)==len(out_files)==1
                and sum(orig_blobs.values())==1 and orig_blobs==out_blobs
                and row["edited_subject_seen"] and row["edited_body_seen"]
            )
            row["status"]="MUTATED_BYTES_PRESERVED" if passed else "SEMANTIC_OR_STRUCTURAL_GAP"
        else:
            passed=False
            row["status"]="NATIVE_MUTATION_BLOCKED"
        verify_bytes(source.read_bytes(),sha,size,version)
        row["source_unchanged"]=True
        print(json.dumps(row,sort_keys=True))
        return 0 if passed else 3

if __name__=="__main__":
    try:raise SystemExit(main())
    except (OSError,ValueError,TypeError):
        print("PUBLIC_FOREIGN_PST_MUTATION_HARNESS_BLOCKED",file=sys.stderr)
        raise SystemExit(1)
