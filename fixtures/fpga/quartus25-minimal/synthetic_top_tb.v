`timescale 1ns/1ps
module synthetic_top_tb;
  reg clk = 0;
  reg reset_n = 0;
  wire led;
  always #10 clk = ~clk;
  synthetic_top #(.TAP(2)) dut (.clk(clk), .reset_n(reset_n), .led(led));
  initial begin
    #25; reset_n = 1;
    #100;
    if (led !== 1'b1) $fatal(1, "expected oscillator counter tap high");
    #100;
    if (led !== 1'b0) $fatal(1, "expected oscillator counter tap low");
    $display("SIM_PASS original synthetic counter");
    $finish;
  end
endmodule
