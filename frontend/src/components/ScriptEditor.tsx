import { memo, useMemo } from "react";
import ReactQuill from "react-quill";
import "react-quill/dist/quill.snow.css";

interface ScriptEditorProps {
  value: string;
  onChange: (value: string) => void;
}

function ScriptEditor({ value, onChange }: ScriptEditorProps) {
  const modules = useMemo(
    () => ({
      toolbar: [
        [{ header: [1, 2, 3, false] }],
        ["bold", "italic", "underline", "strike"],
        [{ list: "ordered" }, { list: "bullet" }],
        ["blockquote", "code-block"],
        ["link"],
        ["clean"],
      ],
      clipboard: {
        matchVisual: false,
      },
    }),
    []
  );

  return (
    <section className="panel script-panel">
      <header className="panel-header">
        <h2>原始脚本</h2>
        <span className="panel-hint">粘贴或编辑原始脚本内容</span>
      </header>
      <div className="panel-body script-editor-body">
        <ReactQuill
          theme="snow"
          value={value}
          onChange={onChange}
          modules={modules}
          readOnly={false}
          placeholder="在此粘贴或输入原始脚本..."
        />
      </div>
    </section>
  );
}

export default memo(ScriptEditor);
