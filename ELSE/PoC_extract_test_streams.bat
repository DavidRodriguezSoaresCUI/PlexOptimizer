@REM ffmpeg -i test.mkv -map 0:0 -c copy test_0.hevc.mkv -map 0:1 -c copy test_1.aac.mkv -map 0:2 -c webvtt test_2.webvtt.mkv
@REM ffmpeg -i test_2.webvtt.mkv -c srt test_2.srt.mkv
@REM ffmpeg -i test_0.hevc.mkv -i test_1.aac.mkv -i test_2.srt.mkv -c copy output.mkv
@REM ffmpeg -i test2.mkv -map 0:V -c copy test2_video.mkv -map 0:a -c copy test2_audio.mkv -map 0:s? -c copy test2_subtitle.mkv -map 0:d? -c copy test2_data.mkv -map 0:t? test2_attachments.mkv
@REM ffmpeg -i test2.mkv -i test2_video.mkv -i test2_audio.mkv -i test2_subtitle.mkv -map 0:t? -c copy -map 1 -c copy -map 2 -c copy -map 3 -c copy output.mkv
@REM echo extracting
@REM ffmpeg -i test2.mkv -map 0:3 -c webvtt test2_3.webvtt.mkv
@REM echo converting
@REM ffmpeg -i test2.mkv -map 0:0 -c:0 h264 -preset fast -crf 22 -map 0:1 -c:1 aac -q:1 1.4 -map 0:2 -c:2 aac -q:2 1.4 test2_converted.mkv
@REM ffmpeg -i test2_3.webvtt.mkv -c srt test2_3.srt.mkv
@REM echo Test: piping extraction then conversion
@REM ffmpeg -i test2.mkv -map 0:3 -c webvtt -f matroska - | ffmpeg -f matroska -i - -c srt test2_3.srt.mkv
@REM echo test2.mkv --[ffmpeg]-> mp4 --[mp4box]-> mp4
@REM ffmpeg -loglevel error -stats -i test2.mkv -map 0:0 -c:0 h264 -preset fast -crf 22 -map 0:1 -c:1 aac -q:1 1.4 -map 0:2 -c:2 aac -q:2 1.4 -map 0:s -c:s mov_text -map -0:12 -map -0:13 test2_converted.mp4
@REM mp4box -add test2_converted.mp4 test2_converted.mp4.mp4
echo NOTE: * --[ffmpeg]-> mp4 produces file with recalculated metadata
echo NOTE: * --[ffmpeg]-> mkv produces file with NON-recalculated metadata
echo echo test2.mkv --[ffmpeg]-> mkv --[mkvmerge]-> mkv
ffmpeg -loglevel error -stats -i test2.mkv -map 0:0 -c:0 h264 -preset fast -crf 22 -map 0:1 -c:1 aac -q:1 1.4 -map 0:2 -c:2 aac -q:2 1.4 -map 0:s -c:s webvtt -map -0:12 -map -0:13 test2_converted.mkv
mkvmerge -o test2_converted.mkv.mkv test2_converted.mkv






