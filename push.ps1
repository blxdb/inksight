# 构建 & 推送 InkSight Docker 镜像到共绩算力 Harbor 仓库
# 用法: 在 PowerShell 中运行 .\push.ps1
# 前置条件: 已执行 docker login harborpush.suanleme.cn

$ImageName   = "inksight-processor"
$Registry    = "harborpush.suanleme.cn/wangduoduo2026"
$Tag         = "v1"

Write-Host "===== 构建 $ImageName =====" -ForegroundColor Cyan
docker build -t $ImageName .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 构建失败！" -ForegroundColor Red
    exit 1
}

Write-Host "`n===== 打标签 =====" -ForegroundColor Cyan
docker tag $ImageName "${Registry}/${ImageName}:${Tag}"
docker tag $ImageName "${Registry}/${ImageName}:latest"

Write-Host "`n===== 推送至 Harbor =====" -ForegroundColor Cyan
Write-Host "   ${Registry}/${ImageName}:${Tag}" -ForegroundColor Yellow
docker push "${Registry}/${ImageName}:${Tag}"
docker push "${Registry}/${ImageName}:latest"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ 完成！" -ForegroundColor Green
    Write-Host "   镜像: ${Registry}/${ImageName}:${Tag}" -ForegroundColor Green
    Write-Host ""
    Write-Host "在共绩算力控制台创建 Job 时填写:"
    Write-Host "  镜像地址: ${Registry}/${ImageName}:${Tag}"
    Write-Host "  启动命令: (留空, 使用 ENTRYPOINT)"
}
