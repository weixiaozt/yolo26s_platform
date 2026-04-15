@echo off
set BACKUP_DIR=D:\yolo26s_platform\backups
set DATE=%date:~0,4%%date:~5,2%%date:~8,2%
if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
mysqldump -u root -p123456 yolo_seg > %BACKUP_DIR%\backup_%DATE%.sql
echo 备份完成: %BACKUP_DIR%\backup_%DATE%.sql
pause
