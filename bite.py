import dis
import marshal

# .pycファイルからコードオブジェクトを読み込む場合
# (ヘッダーサイズはPythonのバージョンにより異なりますが、通常16バイト程度)
f = open('vibe_checker.pyc', 'rb')
f.read(16) 
code_obj = marshal.load(f)
dis.dis(code_obj)