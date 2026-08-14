@echo off
chcp 65001 >nul

:: 激活 conda 环境
call conda activate xiaozhi

:: 检查是否激活成功
if errorlevel 1 (
    echo 错误：无法激活 conda 环境 'xiaozhi'
    echo 请确认环境名称是否正确，或先运行 conda init
    pause
    exit /b 1
)

echo 当前 Conda 环境: %CONDA_DEFAULT_ENV%
echo 开始转换当前目录下的文件...

:: 批量转换文件
for %%f in (*.pdf *.docx *.xlsx *.doc) do (
    echo 正在转换: %%f
    markitdown "%%f" > "%%~nf.md"
)

echo 所有文件转换完成！
pause