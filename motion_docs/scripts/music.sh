#!/usr/bin/env bash
# Sintetiza a trilha ambiente (pad suave em loop) com ffmpeg: 4 acordes
# (Cmaj9, Am9, Fmaj7, G6) com crossfade, eco leve e passa-baixa.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
chord() { # $1 = nome, demais = frequências
  local name=$1; shift
  local expr=""
  for f in "$@"; do
    expr+="0.16*sin(2*PI*$f*t)+0.08*sin(2*PI*$f*1.003*t)+0.03*sin(2*PI*$f*2*t)+"
  done
  ffmpeg -v error -y -f lavfi -i "aevalsrc='(${expr}0)*(0.8+0.2*sin(2*PI*0.25*t))':s=44100:d=8" \
    -af "afade=t=in:d=2.5,afade=t=out:st=5.5:d=2.5" "$tmp/$name.wav"
}
chord c 130.81 196.00 246.94 293.66 329.63
chord a 110.00 164.81 196.00 246.94 261.63
chord f 87.31 174.61 220.00 261.63 329.63
chord g 98.00 196.00 246.94 293.66 329.63
ffmpeg -v error -y -i "$tmp/c.wav" -i "$tmp/a.wav" -i "$tmp/f.wav" -i "$tmp/g.wav" -filter_complex \
  "[0][1]acrossfade=d=2[x];[x][2]acrossfade=d=2[y];[y][3]acrossfade=d=2,aecho=0.8:0.7:180|360:0.35|0.2,lowpass=f=1600,highpass=f=60,volume=0.9,loudnorm=I=-24:TP=-3" \
  -ac 2 -b:a 160k public/music/pad.mp3
rm -rf "$tmp"
echo "public/music/pad.mp3"
